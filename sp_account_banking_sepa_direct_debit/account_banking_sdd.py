##############################################################################
#
# SEPA Direct Debit module for OpenERP
#    Copyright (C) 2013 Akretion (http://www.akretion.com)
#    @author: Alexis de Lattre <alexis.delattre@akretion.com>
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
##############################################################################
from openerp.osv import osv, orm, fields
from openerp.tools.translate import _
from openerp.addons.decimal_precision import decimal_precision as dp
from openerp import SUPERUSER_ID
from unidecode import unidecode
from datetime import datetime
from datetime import date
from openerp.tools.misc import DEFAULT_SERVER_DATE_FORMAT
from dateutil.relativedelta import relativedelta
import logging
import workdays
from openerp import netsvc

NUMBER_OF_UNUSED_MONTHS_BEFORE_EXPIRY = 36

logger = logging.getLogger(__name__)


def acceptgiro_compute(number):
    """
    Create a valid betalingskenmerk for the Dutch rabobank.
 
    Generates a 16 digit number for the number received. The number should be a 15 digit long string.
    There are no checks to validate the number.
 
    :param number: String of numbers to convert to valid betalingskenmerk
    :return: 16 digit long string with a valid betalingskenmerk
    """

    # First, pad the number with zeroes:
    number = (15 - len(number)) * '0' + number

    # Multiply the numbers from right to left with the repeating range: 2, 4, 8, 5, 10, 9, 7, 3, 6, 1
    # (Yes, this is the non-pythonic way, but it works.
    weightedsum = 0
    weightedsum += int(number[14]) * 2
    weightedsum += int(number[13]) * 4
    weightedsum += int(number[12]) * 8
    weightedsum += int(number[11]) * 5
    weightedsum += int(number[10]) * 10
    weightedsum += int(number[9]) * 9
    weightedsum += int(number[8]) * 7
    weightedsum += int(number[7]) * 3
    weightedsum += int(number[6]) * 6
    weightedsum += int(number[5]) * 1
    weightedsum += int(number[4]) * 2
    weightedsum += int(number[3]) * 4
    weightedsum += int(number[2]) * 8
    weightedsum += int(number[1]) * 5
    weightedsum += int(number[0]) * 10

    # Generate checksum digit
    controlegetal = 11 - (weightedsum % 11)
    if controlegetal == 10:
        controlegetal = '1'
    elif controlegetal == 11:
        controlegetal = '0'
    else:
        controlegetal = str(controlegetal)

    number = ''.join((controlegetal, number))
    return number


class banking_export_sdd(orm.Model):
    '''SEPA Direct Debit export'''
    _name = 'banking.export.sdd'
    _description = __doc__
    _rec_name = 'filename'

    def _generate_filename(self, cr, uid, ids, name, arg, context=None):
        res = {}
        for sepa_file in self.browse(cr, uid, ids, context=context):
            ref = sepa_file.payment_order_ids[0].reference
            if ref:
                label = unidecode(ref.replace('/', '-'))
            else:
                label = 'error'
            res[sepa_file.id] = 'sdd_%s.xml' % label
        return res

    _columns = {
        'payment_order_ids': fields.many2many(
            'payment.order',
            'account_payment_order_sdd_rel',
            'banking_export_sepa_id', 'account_order_id',
            'Payment Orders',
            readonly=True),
        'nb_transactions': fields.integer(
            'Number of Transactions', readonly=True),
        'total_amount': fields.float(
            'Total Amount', digits_compute=dp.get_precision('Account'),
            readonly=True),
        'batch_booking': fields.boolean(
            'Batch Booking', readonly=True,
            help="If true, the bank statement will display only one credit "
                 "line for all the direct debits of the SEPA file ; if false, "
                 "the bank statement will display one credit line per direct "
                 "debit of the SEPA file."),
        'charge_bearer': fields.selection([
            ('SLEV', 'Following Service Level'),
            ('SHAR', 'Shared'),
            ('CRED', 'Borne by Creditor'),
            ('DEBT', 'Borne by Debtor'),
        ], 'Charge Bearer', readonly=True,
            help="Following service level : transaction charges are to be "
                 "applied following the rules agreed in the service level and/or "
                 "scheme (SEPA Core messages must use this). Shared : "
                 "transaction charges on the creditor side are to be borne by "
                 "the creditor, transaction charges on the debtor side are to be "
                 "borne by the debtor. Borne by creditor : all transaction "
                 "charges are to be borne by the creditor. Borne by debtor : "
                 "all transaction charges are to be borne by the debtor."),
        'create_date': fields.datetime('Generation Date', readonly=True),
        'file': fields.binary('SEPA File', readonly=True),
        'filename': fields.function(
            _generate_filename, type='char', size=256,
            string='Filename', readonly=True, store=True),
        'state': fields.selection([
            ('draft', 'Draft'),
            ('sent', 'Sent'),
            ('done', 'Reconciled'),
        ], 'State', readonly=True),
    }

    _defaults = {
        'state': 'draft',
    }


class sdd_mandate(orm.Model):
    '''SEPA Direct Debit Mandate'''
    _name = 'sdd.mandate'
    _description = __doc__
    _rec_name = 'unique_mandate_reference'
    _inherit = ['mail.thread']
    _order = 'signature_date desc'
    _track = {
        'state': {
            'account_banking_sepa_direct_debit.mandate_valid':
                lambda self, cr, uid, obj, ctx=None:
                obj['state'] == 'valid',
            'account_banking_sepa_direct_debit.mandate_expired':
                lambda self, cr, uid, obj, ctx=None:
                obj['state'] == 'expired',
            'account_banking_sepa_direct_debit.mandate_cancel':
                lambda self, cr, uid, obj, ctx=None:
                obj['state'] == 'cancel',
        },
        'recurrent_sequence_type': {
            'account_banking_sepa_direct_debit.recurrent_sequence_type_first':
                lambda self, cr, uid, obj, ctx=None:
                obj['recurrent_sequence_type'] == 'first',
            'account_banking_sepa_direct_debit.'
            'recurrent_sequence_type_recurring':
                lambda self, cr, uid, obj, ctx=None:
                obj['recurrent_sequence_type'] == 'recurring',
            'account_banking_sepa_direct_debit.recurrent_sequence_type_final':
                lambda self, cr, uid, obj, ctx=None:
                obj['recurrent_sequence_type'] == 'final',
        }
    }

    _columns = {
        'partner_bank_id': fields.many2one(
            'res.partner.bank', 'Bank Account', track_visibility='onchange'),
        'partner_id': fields.related(
            'partner_bank_id', 'partner_id', type='many2one',
            relation='res.partner', string='Partner', readonly=True),
        'company_id': fields.many2one('res.company', 'Company', required=True),
        'unique_mandate_reference': fields.char(
            'Unique Mandate Reference', size=35, readonly=True,
            track_visibility='always'),
        'type': fields.selection([
            ('recurrent', 'Recurrent'),
            ('oneoff', 'One-Off'),
        ], 'Type of Mandate', required=True, track_visibility='always'),
        'recurrent_sequence_type': fields.selection([
            ('first', 'First'),
            ('recurring', 'Recurring'),
            ('final', 'Final'),
        ], 'Sequence Type for Next Debit', track_visibility='onchange',
            help="This field is only used for Recurrent mandates, not for "
                 "One-Off mandates."),
        'signature_date': fields.date(
            'Date of Signature of the Mandate', track_visibility='onchange'),
        'scan': fields.binary('Scan of the Mandate'),
        'last_debit_date': fields.date(
            'Date of the Last Debit', readonly=True),
        'state': fields.selection([
            ('draft', 'Draft'),
            ('valid', 'Valid'),
            ('expired', 'Expired'),
            ('cancel', 'Cancelled'),
        ], 'Status',
            help="Only valid mandates can be used in a payment line. A "
                 "cancelled mandate is a mandate that has been cancelled by "
                 "the customer. A one-off mandate expires after its first use. "
                 "A recurrent mandate expires after it's final use or if it "
                 "hasn't been used for 36 months."),
        'payment_line_ids': fields.one2many(
            'payment.line', 'sdd_mandate_id', "Related Payment Lines"),
        'sepa_migrated': fields.boolean(
            'Migrated to SEPA', track_visibility='onchange',
            help="If this field is not active, the mandate section of the "
                 "next direct debit file that include this mandate will contain "
                 "the 'Original Mandate Identification' and the 'Original "
                 "Creditor Scheme Identification'. This is required in a few "
                 "countries (Belgium for instance), but not in all countries. "
                 "If this is not required in your country, you should keep this "
                 "field always active."),
        'original_mandate_identification': fields.char(
            'Original Mandate Identification', size=35,
            track_visibility='onchange',
            help="When the field 'Migrated to SEPA' is not active, this "
                 "field will be used as the Original Mandate Identification in "
                 "the Direct Debit file."),
    }

    _defaults = {
        'company_id': lambda self, cr, uid, context:
        self.pool['res.company']._company_default_get(
            cr, uid, 'sdd.mandate', context=context),
        'unique_mandate_reference': lambda self, cr, uid, ctx:
        self.pool['ir.sequence'].get(cr, uid, 'sdd.mandate.reference'),
        'state': 'draft',
        'sepa_migrated': True,
    }

    _sql_constraints = [(
                            'mandate_ref_company_uniq',
                            'unique(unique_mandate_reference, company_id)',
                            'A Mandate with the same reference already exists for this company !'
                        )]

    def _check_sdd_mandate(self, cr, uid, ids):
        for mandate in self.browse(cr, uid, ids):
            if (mandate.signature_date and
                        mandate.signature_date >
                        datetime.today().strftime('%Y-%m-%d')):
                raise orm.except_orm(
                    _('Error:'),
                    _("The date of signature of mandate '%s' is in the "
                      "future !")
                    % mandate.unique_mandate_reference)
            if mandate.state == 'valid' and not mandate.signature_date:
                raise orm.except_orm(
                    _('Error:'),
                    _("Cannot validate the mandate '%s' without a date of "
                      "signature.")
                    % mandate.unique_mandate_reference)
            if mandate.state == 'valid' and not mandate.partner_bank_id:
                raise orm.except_orm(
                    _('Error:'),
                    _("Cannot validate the mandate '%s' because it is not "
                      "attached to a bank account.")
                    % mandate.unique_mandate_reference)

            if (mandate.signature_date and mandate.last_debit_date and
                        mandate.signature_date > mandate.last_debit_date):
                raise orm.except_orm(
                    _('Error:'),
                    _("The mandate '%s' can't have a date of last debit "
                      "before the date of signature.")
                    % mandate.unique_mandate_reference)
            if (mandate.type == 'recurrent'
                and not mandate.recurrent_sequence_type):
                raise orm.except_orm(
                    _('Error:'),
                    _("The recurrent mandate '%s' must have a sequence type.")
                    % mandate.unique_mandate_reference)
            if (mandate.type == 'recurrent' and not mandate.sepa_migrated
                and mandate.recurrent_sequence_type != 'first'):
                raise orm.except_orm(
                    _('Error:'),
                    _("The recurrent mandate '%s' which is not marked as "
                      "'Migrated to SEPA' must have its recurrent sequence "
                      "type set to 'First'.")
                    % mandate.unique_mandate_reference)
            if (mandate.type == 'recurrent' and not mandate.sepa_migrated
                and not mandate.original_mandate_identification):
                raise orm.except_orm(
                    _('Error:'),
                    _("You must set the 'Original Mandate Identification' "
                      "on the recurrent mandate '%s' which is not marked "
                      "as 'Migrated to SEPA'.")
                    % mandate.unique_mandate_reference)
        return True

    _constraints = [
        (_check_sdd_mandate, "Error msg in raise", [
            'last_debit_date', 'signature_date', 'state', 'partner_bank_id',
            'type', 'recurrent_sequence_type', 'sepa_migrated',
            'original_mandate_identification',
        ]),
    ]

    def mandate_type_change(self, cr, uid, ids, type):
        if type == 'recurrent':
            recurrent_sequence_type = 'first'
        else:
            recurrent_sequence_type = False
        res = {'value': {'recurrent_sequence_type': recurrent_sequence_type}}
        return res

    def mandate_partner_bank_change(
            self, cr, uid, ids, partner_bank_id, type, recurrent_sequence_type,
            last_debit_date, state):
        res = {'value': {}}
        if partner_bank_id:
            partner_bank_read = self.pool['res.partner.bank'].read(
                cr, uid, partner_bank_id, ['partner_id'])['partner_id']
            if partner_bank_read:
                res['value']['partner_id'] = partner_bank_read[0]
        if (state == 'valid' and partner_bank_id
            and type == 'recurrent'
            and recurrent_sequence_type != 'first'):
            res['value']['recurrent_sequence_type'] = 'first'
            res['warning'] = {
                'title': _('Mandate update'),
                'message': _(
                    "As you changed the bank account attached to this "
                    "mandate, the 'Sequence Type' has been set back to "
                    "'First'."),
            }
        return res

    def validate(self, cr, uid, ids, context=None):
        to_validate_ids = []
        for mandate in self.browse(cr, uid, ids, context=context):
            assert mandate.state == 'draft', 'Mandate should be in draft state'
            to_validate_ids.append(mandate.id)
        self.write(
            cr, uid, to_validate_ids, {'state': 'valid'}, context=context)
        return True

    def cancel(self, cr, uid, ids, context=None):
        to_cancel_ids = []
        for mandate in self.browse(cr, uid, ids, context=context):
            assert mandate.state in ('draft', 'valid'), \
                'Mandate should be in draft or valid state'
            to_cancel_ids.append(mandate.id)
        self.write(
            cr, uid, to_cancel_ids, {'state': 'cancel'}, context=context)
        return True

    def back2draft(self, cr, uid, ids, context=None):
        to_draft_ids = []
        for mandate in self.browse(cr, uid, ids, context=context):
            assert mandate.state == 'cancel', \
                'Mandate should be in cancel state'
            to_draft_ids.append(mandate.id)
        self.write(
            cr, uid, to_draft_ids, {'state': 'draft'}, context=context)
        return True

    def _sdd_mandate_set_state_to_expired(self, cr, uid, context=None):
        # We are not going to expire mandates.
        return True

        logger.info('Searching for SDD Mandates that must be set to Expired')
        expire_limit_date = datetime.today() + \
                            relativedelta(months=-NUMBER_OF_UNUSED_MONTHS_BEFORE_EXPIRY)
        expire_limit_date_str = expire_limit_date.strftime('%Y-%m-%d')
        expired_mandate_ids = self.search(cr, uid, [
            '|',
            ('last_debit_date', '=', False),
            ('last_debit_date', '<=', expire_limit_date_str),
            ('state', '=', 'valid'),
            ('signature_date', '<=', expire_limit_date_str),
        ], context=context)
        if expired_mandate_ids:
            self.write(
                cr, uid, expired_mandate_ids, {'state': 'expired'},
                context=context)
            logger.info(
                'The following SDD Mandate IDs has been set to expired: %s'
                % expired_mandate_ids)
        else:
            logger.info('0 SDD Mandates must be set to Expired')
        return True


class res_partner_bank(orm.Model):
    _inherit = 'res.partner.bank'

    _columns = {
        'sdd_mandate_ids': fields.one2many(
            'sdd.mandate', 'partner_bank_id', 'SEPA Direct Debit Mandates'),
    }


class payment_line(orm.Model):
    _inherit = 'payment.line'

    def _get_struct_communication_types(self, cr, uid, context=None):
        return [('ISO', 'ISO'), ('CUR', 'CUR')]


    _columns = {
        'sdd_mandate_id': fields.many2one(
            'sdd.mandate', 'SEPA Direct Debit Mandate',
            domain=[('state', '=', 'valid')]),
        'struct_communication_type': fields.selection(
            _get_struct_communication_types, 'Structured Communication Type'),

    }

    _defaults = {
        'struct_communication_type': 'CUR',
    }

    def create(self, cr, uid, vals, context=None):
        '''If the customer invoice has a mandate, take it
        otherwise, take the first valid mandate of the bank account'''
        if context is None:
            context = {}
        if not vals:
            vals = {}
        partner_bank_id = vals.get('bank_id')
        move_line_id = vals.get('move_line_id')
        if (context.get('default_payment_order_type') == 'debit'
            and 'sdd_mandate_id' not in vals):
            if move_line_id:
                line = self.pool['account.move.line'].browse(
                    cr, uid, move_line_id, context=context)
                if (line.invoice and line.invoice.type == 'out_invoice'
                    and line.invoice.sdd_mandate_id):
                    vals.update({
                        'sdd_mandate_id': line.invoice.sdd_mandate_id.id,
                        'bank_id': line.invoice.sdd_mandate_id.partner_bank_id.id,
                    })
                    if 'communication' not in vals:
                        vals.update({'communication': line.invoice.name})

            if partner_bank_id and 'sdd_mandate_id' not in vals:
                mandate_ids = self.pool['sdd.mandate'].search(cr, uid, [
                    ('partner_bank_id', '=', partner_bank_id),
                    ('state', '=', 'valid'),
                ], context=context)
                if mandate_ids:
                    vals['sdd_mandate_id'] = mandate_ids[0]
        return super(payment_line, self).create(cr, uid, vals, context=context)

    def _check_mandate_bank_link(self, cr, uid, ids):
        for payline in self.browse(cr, uid, ids):
            if (payline.sdd_mandate_id and payline.bank_id
                and payline.sdd_mandate_id.partner_bank_id.id !=
                    payline.bank_id.id):
                raise orm.except_orm(
                    _('Error:'),
                    _("The payment line with reference '%s' has the bank "
                      "account '%s' which is not attached to the mandate "
                      "'%s' (this mandate is attached to the bank account "
                      "'%s').") % (
                        payline.name,
                        self.pool['res.partner.bank'].name_get(
                            cr, uid, [payline.bank_id.id])[0][1],
                        payline.sdd_mandate_id.unique_mandate_reference,
                        self.pool['res.partner.bank'].name_get(
                            cr, uid,
                            [payline.sdd_mandate_id.partner_bank_id.id])[0][1],
                    ))
        return True

    _constraints = [
        (_check_mandate_bank_link, 'Error msg in raise',
         ['sdd_mandate_id', 'bank_id']),
    ]



class payment_order_create(orm.TransientModel):
    _inherit = "payment.order.create"

    _columns = {
        # 'sp_type': fields.selection([('SP Lidmaatschap', 'SP Lidmaatschap'),
        #                              ('SP Lidmaatschap ROOD', 'SP Lidmaatschap ROOD'),
        #                              ('Donatie', 'Donatie')],
        #                             'SP Type', required=False),
        'sp_type': fields.many2one('account.journal', 'Type',
                                   domain="[('type', '=', 'sale'), ('view_direct_debit', '=', True)]"),
    }


class account_invoice(orm.Model):
    _inherit = 'account.invoice'

    def validate_crm_payment(self, cr, uid, ids, order, context=None):
        mv_obj = self.pool.get('account.move')
        mv_line_obj = self.pool.get('account.move.line')
        for invoice in self.browse(cr, uid, ids, context):
            c = context.copy()
            c['novalidate'] = True

            if invoice.state == 'open':
                period_id = self.pool.get('account.period').find(cr, uid, dt=order.date_sent, context=c)
                if len(period_id) != 1:
                    raise osv.except_osv(_('Configuration Error !'), _('More then one period found for this date'))

                c['period_id'] = period_id[0]

                mv = order.sdd_move_id
                mv_id = order.sdd_move_id.id
                logger.info('Creating moves, first debit')
                debit_mv_line_vals = {
                    'period_id': period_id[0],
                    'date': order.date_sent,
                    'move_id': mv_id,
                    'name': invoice.number,
                    'ref': mv.name.replace('/',''),
                    'partner_id': invoice.partner_id.id,
                    'account_id': order.mode.transfer_account_id.id,
                    'debit': invoice.residual,
                    'state': 'valid',  # This state: valid is a dirty dirty hack (See below)
                }
                debit_mv_line_id = mv_line_obj.create(cr, uid, debit_mv_line_vals, context=c)
                logger.info('Creating moves, nog credit')
                credit_mv_line_vals = {
                    'period_id': period_id[0],
                    'date': order.date_sent,
                    'move_id': mv_id,
                    'name': invoice.number,
                    'ref': mv.name.replace('/',''),
                    'partner_id': invoice.partner_id.id,
                    'account_id': invoice.account_id.id,
                    'credit': invoice.residual,
                    'quantity': 1,
                    'state': 'valid',  # This state: valid is a dirty dirty hack (See below)
                }
                # We force a state: valid in the line. We do this because we create massive account.move entries
                # With 6000 lines. With the novalidate = True we disable checking the account.move because this can
                # take up to a minute in the end for *every* new move line.
                # If the state is not valid for the recociliation we cannot reconcile the entry
                credit_mv_line_id = mv_line_obj.create(cr, uid, credit_mv_line_vals, context=c)

                logger.info('Invoice move lines %s created' % (invoice.number,))

                # Find the invoice move line to reconcile
                rec_line_id = False
                for line in invoice.move_id.line_id:
                    if line.account_id == invoice.account_id:
                        rec_line_id = line.id
                # If no recociliation account could be found
                if not rec_line_id:
                    raise osv.except_osv(_('Error!'), _('No recociliation account could be found for the journal entry:'%(invoice.move_id.name)))

                reconcile_ids = [credit_mv_line_id, rec_line_id]

                # Reconcile the journal entry
                mv_line_obj.reconcile(cr, uid, reconcile_ids, 'auto', False, False, False, context=context)
                logger.info('Diret Debit Invoice Reconciliation done for invoice %s' % (invoice.number,))





    def validate_sdd_payment(self, cr, uid, ids, context=None):
        raise NotImplementedError("This method is no longer implemeted, use validate_crm_payment")
        voucher_ids = []
        for invoice in self.browse(cr, uid, ids, context):
            jrn_obj = self.pool.get('account.journal')
            jrn = jrn_obj.browse(cr, uid, context['journal_id'])

            voucher_vals = {
                'type': 'receipt',
                'name': invoice.number,
                'partner_id': invoice.partner_id.id,
                'journal_id': jrn.id,
                'account_id': jrn.default_credit_account_id.id,
                'company_id': invoice.company_id.id,
                'currency_id': invoice.company_id.currency_id.id,
                'date': datetime.today(),
                'amount': invoice.residual,
                'line_amount': invoice.residual,
                # Remove period_id, use the date from today.
                # Request by peter.
                # 'period_id': invoice.period_id.id,
            }
            voucher_vals.update(self.pool.get('account.voucher').onchange_partner_id(cr, uid, [],
                                                                                     partner_id=invoice.partner_id.id,
                                                                                     journal_id=jrn.id,
                                                                                     amount=invoice.residual,
                                                                                     currency_id=invoice.company_id.currency_id.id,
                                                                                     ttype='receipt',
                                                                                     date=datetime.today(),
                                                                                     context=context
                                                                                     )['value'])
            line_drs = []
            for line_dr in voucher_vals['line_dr_ids']:
                line_drs.append((0, 0, line_dr))
            voucher_vals['line_dr_ids'] = line_drs
            line_crs = []
            invoice_line_ids = [move_id.id for move_id in invoice.move_id.line_id]
            for line_cr in voucher_vals['line_cr_ids']:
                if line_cr['move_line_id'] in invoice_line_ids:
                    # Only append this invoice, not all the invoices of this partner
                    line_cr['amount'] = line_cr['amount_original']
                    line_crs.append((0, 0, line_cr))
            voucher_vals['line_cr_ids'] = line_crs
            voucher_vals['reference'] = context['sale_order_reference']
            voucher_id = self.pool.get('account.voucher').create(cr, uid, voucher_vals, context=context)
            voucher_ids.append(voucher_id)

        move_id = self.pool.get('account.voucher').action_single_move_line_create(cr, uid, voucher_ids, context=context)
        return move_id

    _columns = {
        'sdd_mandate_id': fields.many2one(
            'sdd.mandate', 'SEPA Direct Debit Mandate',
            domain=[('state', '=', 'valid')], readonly=True,
            states={'draft': [('readonly', False)]}),
        'sdd_payment_sent': fields.boolean('SDD Payment Requested'),
        'acceptgiro_code': fields.char('Acceptgiro Code', size=16),
    }

    def create(self, cr, uid, vals, context=None):
        invoice_id = super(account_invoice, self).create(cr, uid, vals, context=context)
        inv_id = str(invoice_id).zfill(15)
        print "INVID:", inv_id
        agiro = acceptgiro_compute(inv_id)
        print "AGIRO:", agiro
        self.write(cr, uid, [invoice_id], {'acceptgiro_code': agiro})
        return invoice_id


    def copy(self, cr, uid, ids, default=None, context=None):
        default['sdd_payment_sent'] = False
        return super(account_invoice, self).copy(cr, uid, ids, default=default, context=context)

class account_voucher(orm.Model):
    _inherit = 'account.voucher'

    def action_single_move_line_create(self, cr, uid, ids, context=None):
        '''
        Confirm the vouchers given in ids and create the journal entries for each of them
        '''
        if context is None:
            context = {}
        move_pool = self.pool.get('account.move')
        move_line_pool = self.pool.get('account.move.line')
        # Create the first item
        voucher_1 = self.browse(cr, uid, ids[0], context=context)
        local_context = dict(context, force_company=voucher_1.journal_id.company_id.id)
        company_currency = self._get_company_currency(cr, uid, voucher_1.id, context)
        current_currency = self._get_current_currency(cr, uid, voucher_1.id, context)
        # we select the context to use accordingly if it's a multicurrency case or not
        context = self._sel_context(cr, uid, voucher_1.id, context)
        # But for the operations made by _convert_amount, we always need to give the date in the context
        ctx = context.copy()
        ctx.update({'date': voucher_1.date})
        # Create the account move record.
        move_id = move_pool.create(cr, uid, self.account_move_get(cr, uid, voucher_1.id, context=context), context=context)
        print "creating new move_id in action_single_move_line_create", move_id
        # Get the name of the account_move just created
        name = move_pool.browse(cr, uid, move_id, context=context).name
        # Disable validating every new move line
        local_context['novalidate'] = True

        total_rec_list_ids = []
        for voucher in self.browse(cr, uid, ids, context=context):
            # Create the first line of the voucher
            move_line_id = move_line_pool.create(cr, uid, self.first_move_line_get(cr,uid,voucher.id, move_id, company_currency, current_currency, local_context), local_context)
            print "Creating a new move line A: ", move_line_id
            move_line_brw = move_line_pool.browse(cr, uid, move_line_id, context=context)
            line_total = move_line_brw.debit - move_line_brw.credit
            rec_list_ids = []

            if voucher.type == 'sale':
                line_total = line_total - self._convert_amount(cr, uid, voucher.tax_amount, voucher.id, context=ctx)
            elif voucher.type == 'purchase':
                line_total = line_total + self._convert_amount(cr, uid, voucher.tax_amount, voucher.id, context=ctx)
            # Create one move line per voucher line where amount is not 0.0
            # Deze ondeste dus vaker aanroepen per voicher?
            line_total, rec_list_ids = self.voucher_move_line_create(cr, uid, voucher.id, line_total, move_id, company_currency, current_currency, context)
            print "Creating a new move line B: line_total, "
            print "created line_total", line_total
            print "rec_list_ids ", rec_list_ids
            total_rec_list_ids.append(rec_list_ids[0])
            # Create the writeoff line if needed
            print "line total", line_total
            ml_writeoff = self.writeoff_move_line_get(cr, uid, voucher.id, line_total, move_id, name, company_currency, current_currency, local_context)
            print "ml_writeoff", ml_writeoff
            if ml_writeoff:
                move_line_pool.create(cr, uid, ml_writeoff, local_context)
            # We post the voucher.
            self.write(cr, uid, [voucher.id], {
                'move_id': move_id,
                'state': 'posted',
                'number': name,
            })
        # Enable novalidate again for the next steps
        del(local_context['novalidate'])

        if voucher.journal_id.entry_posted:
            print "Posting move id", move_id
            move_pool.post(cr, uid, [move_id], context={})
        # We automatically reconcile the account move lines.
        reconcile = False
        for rec_ids in total_rec_list_ids:
            if len(rec_ids) >= 2:
                reconcile = move_line_pool.reconcile_partial(cr, uid, rec_ids, writeoff_acc_id=voucher.writeoff_acc_id.id, writeoff_period_id=voucher.period_id.id, writeoff_journal_id=voucher.journal_id.id)
        return move_id


class payment_order(orm.Model):
    _inherit = "payment.order"

    _columns = {
        'sdd_move_id': fields.many2one('account.move', 'Overschrijf boeking', readonly=True),
        'first_move_id': fields.many2one('account.move', 'Incasso boeking, First', readonly=True),
        'rcur_move_id': fields.many2one('account.move', 'Incasso boeking, Recurring', readonly=True),
    }

    def payment_order_split(self, cr, uid, ids, context=None):
        icp_obj = self.pool['ir.config_parameter']

        split_count = int(icp_obj.get_param(cr, SUPERUSER_ID, 'sp_account_banking_sepa_direct_debit.split_count', 3000))

        for po in self.browse(cr, uid, ids):
            line_ids = po.line_ids
            line_ids = self.read(cr, uid, [po.id], fields=['line_ids'], context=context)[0]['line_ids']
            print "LINE IDS:", line_ids

            if len(line_ids) > split_count:
                lines = map(None, *([iter(line_ids)] * split_count))
                orig = True
                for l in lines:
                    if orig:
                        orig = False
                        continue
                    l_ids = list(filter(None, l))
                    print "L_IDS:", l_ids
                    new_po_id = self.copy(cr, uid, po.id, {})
                    self.pool.get('payment.line').write(cr, uid, l_ids, {'order_id': new_po_id})

    def button_add_sdd_invoices(self, cr, uid, ids, context=None):
        view_id = self.pool.get('ir.ui.view').search(cr, uid, [('model', '=', 'sdd.add.payment'),
                                                               ('name', '=', 'sp.sdd.add.payment.view')])

        order = self.browse(cr, uid, ids)[0]
        if order.id:
            context['default_payment_order_id'] = order.id
            context['default_due_date'] = datetime.today().strftime('%Y-%m-%d')

            return {
                'type': 'ir.actions.act_window',
                'name': 'Toevoegen SDD facturen',
                'view_mode': 'form',
                'view_type': 'form',
                'view_id': view_id[0],
                'res_model': 'sdd.add.payment',
                'target': 'new',
                'context': context,
            }


payment_order()




class sdd_add_payment(orm.TransientModel):
    _name = 'sdd.add.payment'

    _columns = {
        'payment_order_id': fields.many2one('payment.order', 'Payment order', select=True),
        'due_date': fields.date('Factuurdatum', required=True),
        # 'sp_type': fields.selection([('SP Lidmaatschap','SP Lidmaatschap'),('SP Lidmaatschap ROOD','SP Lidmaatschap ROOD'),('Donatie','Donatie')],'SP Type', required=True),
        'sp_type': fields.many2one('account.journal', 'Type',
                                   domain="[('type', '=', 'sale'), ('view_direct_debit', '=', True)]"),
    }

    def _set_due_date(self, cr, uid, inv, context):
        # And, now we have to set the date_due to compy with Sepa stuff.
        # We do this for every invoice
        print "date-due now is", inv.date_due
        if inv.sdd_mandate_id.recurrent_sequence_type == 'recurring':
            # Recurring mandate, setting date to to invoice data, but only if the invoice date is
            # 3 days into the future! Otherwise add 3 working days
            date_invoice = datetime.strptime(inv.date_invoice, DEFAULT_SERVER_DATE_FORMAT)
            difference = workdays.networkdays(date.today(), date_invoice.date())
            print "En het verschil is", difference

            # If invoicedate == today, difference == 1
            # If invoicedate == tomorrow, difference == 2
            # networkdays is inclusive, so workdays.networkdays(date.today(), date.today()) == 1
            # We need a minimum difference of 3 real days, 4 networkdays
            if difference < 5:
                # Difference isn't enough, setting the difference from today date
                date_due = workdays.workday(datetime.now(), 5).date()
            else:
                # Difference is good
                date_due = date_invoice.date()
        else:
            # First mandate, this needs at least six working days, at the SP we decided to pick 14 days,
            # that's ten working days.
            date_invoice = datetime.strptime(inv.date_invoice, DEFAULT_SERVER_DATE_FORMAT)
            difference = workdays.networkdays(date.today(), date_invoice.date())
            print "En het verschil is", difference
            if difference < 7:
                # Difference isn't enough, setting the difference from today date
                date_due = workdays.workday(datetime.now(), 7).date()
            else:
                # Difference is good
                date_due = date_invoice.date()
        print "new date due is", date_due
        date_due = date_due.strftime(DEFAULT_SERVER_DATE_FORMAT)
        print "En als string", date_due
        # Setting new date_due on the invoice:
        # inv.write(cr, uid, inv.id, {'date_due': date_due}, context=context)
        inv.write({'date_due': date_due})
        # inv.date_due = date_due

        # And on the move lines. Only update the receivable line, that's the only line that has a due date

        for move_line in inv.move_id.line_id:
            if move_line.account_id.type == 'receivable':
                move_line.date_maturity = date_due
                # move_line.write(cr, uid, move_line.id, {'date_maturity': date_due}, context=context)
                move_line.write({'date_maturity': date_due})

        return date_due


    def add_invoices(self, cr, uid, ids, context=None):
        res = {}
        order_line_obj = self.pool.get('payment.line')
        move_obj = self.pool.get('account.move.line')

        wf_service = netsvc.LocalService ( "workflow" )
        for order in self.browse(cr, uid, ids, context):
            # Find invoices, filter on journal type, due date (This is the invoice data) and
            # Only open or draft invoices
            move_ids = []
            if order.sp_type.id:
                inv_ids = self.pool.get('account.invoice').search(cr, uid, [
                    ('journal_id', '=', order.sp_type.id),
                    ('date_invoice', '=', order.due_date),
                    ('state', 'in', ['open', 'draft']),
                    ('sdd_payment_sent', '=', False),

                ])
            else:
                inv_ids = self.pool.get('account.invoice').search(cr, uid, [
                    ('date_invoice', '=', order.due_date),
                    ('state', 'in', ['open', 'draft']),
                    ('sdd_payment_sent', '=', False),
                ])

            print "We have invoice id", inv_ids
            for inv_id in inv_ids:
                inv = self.pool.get('account.invoice').browse(cr, uid, inv_id)
                if inv.sdd_mandate_id:
                    print "Invoice state", inv.state

                    if inv.state == 'draft':
                        # Confirm invoice
                        wf_service.trg_validate(uid, 'account.invoice', inv.id, 'invoice_open', cr)
                        # And reread
                        print "invoice is now in state", inv.state
                    inv = self.pool.get('account.invoice').browse(cr, uid, inv_id)
                    print "After re -read", inv.state

                    # reset due date, after the invoice is confirmed otherwise we have no move lines.
                    inv.date_due = self._set_due_date(cr, uid, inv, context)

                    # We need the moveline in the move.moveline.account_id.type = receivable
                    for move_line in inv.move_id.line_id:
                        if move_line.account_id.type == 'receivable':
                            move_ids.append(move_line.id)
                # Commiting to database we want to see progress
                cr.commit()


            print "MOVE IDS:", move_ids

            line2bank = move_obj.line2bank(cr, uid, move_ids, None, context)

            for line in move_obj.browse(cr, uid, move_ids, context):
                print "AMT:", line.amount_to_pay
                print "DEBIT:", line.debit
                if line.debit > 0.00:
                    if order.payment_order_id.date_prefered == "now":
                        #no payment date => immediate payment
                        date_to_pay = False
                    elif order.payment_order_id.date_prefered == 'due':
                        date_to_pay = line.date_maturity
                    elif order.payment_order_id.date_prefered == 'fixed':
                        date_to_pay = order.payment_order_id.date_scheduled
                    print "Creating with communication", line.ref
                    order_line_obj.create(cr, uid, {
                        'move_line_id': line.id,
                        'amount_currency': line.debit,
                        'bank_id': line2bank.get(line.id),
                        'order_id': order.payment_order_id.id,
                        'partner_id': line.partner_id and line.partner_id.id or False,
                        'communication': line.invoice.name or '/',
                        'name': str(line.invoice.acceptgiro_code) or '/',
                        'state': inv and inv.reference_type != 'none' and 'structured' or 'normal',
                        'date': date_to_pay,
                        'currency': (
                                    inv and inv.currency_id.id) or line.journal_id.currency.id or line.journal_id.company_id.currency_id.id,
                    }, context=context)

        return {'type': 'ir.actions.act_window_close', 'context': context, }
