# -*- encoding: utf-8 -*-
##############################################################################
#
#    SEPA Direct Debit module for OpenERP
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

from openerp.osv import orm, fields, osv
from openerp.tools.translate import _
from openerp import netsvc
from datetime import datetime
from lxml import etree
import collections

import logging
LOGGER = logging.getLogger(__name__)

def checksum(number):
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

class banking_export_sdd_wizard(orm.TransientModel):
    _name = 'banking.export.sdd.wizard'
    _inherit = ['banking.export.pain']
    _description = 'Export SEPA Direct Debit File'
    _columns = {
        'state': fields.selection([
            ('create', 'Create'),
            ('finish', 'Finish'),
            ], 'State', readonly=True),
        'batch_booking': fields.boolean(
            'Batch Booking',
            help="If true, the bank statement will display only one credit "
            "line for all the direct debits of the SEPA file ; if false, "
            "the bank statement will display one credit line per direct "
            "debit of the SEPA file."),
        'charge_bearer': fields.selection([
            ('SLEV', 'Following Service Level'),
            ('SHAR', 'Shared'),
            ('CRED', 'Borne by Creditor'),
            ('DEBT', 'Borne by Debtor'),
            ], 'Charge Bearer', required=True,
            help="Following service level : transaction charges are to be "
            "applied following the rules agreed in the service level and/or "
            "scheme (SEPA Core messages must use this). Shared : transaction "
            "charges on the creditor side are to be borne by the creditor, "
            "transaction charges on the debtor side are to be borne by the "
            "debtor. Borne by creditor : all transaction charges are to be "
            "borne by the creditor. Borne by debtor : all transaction "
            "charges are to be borne by the debtor."),
        'nb_transactions': fields.related(
            'file_id', 'nb_transactions', type='integer',
            string='Number of Transactions', readonly=True),
        'total_amount': fields.related(
            'file_id', 'total_amount', type='float', string='Total Amount',
            readonly=True),
        'file_id': fields.many2one(
            'banking.export.sdd', 'SDD File', readonly=True),
        'file': fields.related(
            'file_id', 'file', string="File", type='binary', readonly=True),
        'filename': fields.related(
            'file_id', 'filename', string="Filename", type='char', size=256,
            readonly=True),
        'payment_order_ids': fields.many2many(
            'payment.order', 'wiz_sdd_payorders_rel', 'wizard_id',
            'payment_order_id', 'Payment Orders', readonly=True),
        }

    _defaults = {
        'charge_bearer': 'SLEV',
        'state': 'create',
        }

    def create(self, cr, uid, vals, context=None):
        payment_order_ids = context.get('active_ids', [])
        vals.update({
            'payment_order_ids': [[6, 0, payment_order_ids]],
        })
        return super(banking_export_sdd_wizard, self).create(
            cr, uid, vals, context=context)

    def _get_previous_bank(self, cr, uid, payline, context=None):
        payline_obj = self.pool['payment.line']
        previous_bank = False
        payline_ids = payline_obj.search(
            cr, uid, [
                ('sdd_mandate_id', '=', payline.sdd_mandate_id.id),
                ('bank_id', '!=', payline.bank_id.id),
            ],
            context=context)
        if payline_ids:
            older_lines = payline_obj.browse(
                cr, uid, payline_ids, context=context)
            previous_date = False
            previous_payline_id = False
            for older_line in older_lines:
                older_line_date_sent = older_line.order_id.date_sent
                if (older_line_date_sent
                        and older_line_date_sent > previous_date):
                    previous_date = older_line_date_sent
                    previous_payline_id = older_line.id
            if previous_payline_id:
                previous_payline = payline_obj.browse(
                    cr, uid, previous_payline_id, context=context)
                previous_bank = previous_payline.bank_id
        return previous_bank

    def create_sepa(self, cr, uid, ids, context=None):
        '''
        Creates the SEPA Direct Debit file. That's the important code !
        '''
        sepa_export = self.browse(cr, uid, ids[0], context=context)

        pain_flavor = sepa_export.payment_order_ids[0].mode.type.code
        convert_to_ascii = \
            sepa_export.payment_order_ids[0].mode.convert_to_ascii
        if pain_flavor == 'pain.008.001.02':
            bic_xml_tag = 'BIC'
            name_maxsize = 70
            root_xml_tag = 'CstmrDrctDbtInitn'
        elif pain_flavor == 'pain.008.001.03':
            bic_xml_tag = 'BICFI'
            name_maxsize = 140
            root_xml_tag = 'CstmrDrctDbtInitn'
        elif pain_flavor == 'pain.008.001.04':
            bic_xml_tag = 'BICFI'
            name_maxsize = 140
            root_xml_tag = 'CstmrDrctDbtInitn'
        else:
            raise orm.except_orm(
                _('Error:'),
                _("Payment Type Code '%s' is not supported. The only "
                    "Payment Type Code supported for SEPA Direct Debit "
                    "are 'pain.008.001.02', 'pain.008.001.03' and "
                    "'pain.008.001.04'.") % pain_flavor)

        gen_args = {
            'bic_xml_tag': bic_xml_tag,
            'name_maxsize': name_maxsize,
            'convert_to_ascii': convert_to_ascii,
            'payment_method': 'DD',
            'pain_flavor': pain_flavor,
            'sepa_export': sepa_export,
            'file_obj': self.pool['banking.export.sdd'],
            'pain_xsd_file':
            'account_banking_sepa_direct_debit/data/%s.xsd' % pain_flavor,
        }

        pain_ns = {
            'xsi': 'http://www.w3.org/2001/XMLSchema-instance',
            None: 'urn:iso:std:iso:20022:tech:xsd:%s' % pain_flavor,
            }

        xml_root = etree.Element('Document', nsmap=pain_ns)
        pain_root = etree.SubElement(xml_root, root_xml_tag)

        # A. Group header
        group_header_1_0, nb_of_transactions_1_6, control_sum_1_7 = \
            self.generate_group_header_block(
                cr, uid, pain_root, gen_args, context=context)

        transactions_count_1_6 = 0
        total_amount = 0.0
        amount_control_sum_1_7 = 0.0
        lines_per_group = {}
        # key = (requested_date, priority, sequence type)
        # value = list of lines as objects
        # Iterate on payment orders
        today = fields.date.context_today(self, cr, uid, context=context)
        for payment_order in sepa_export.payment_order_ids:
            total_amount = total_amount + payment_order.total
            # Iterate each payment lines
            for line in payment_order.line_ids:
                transactions_count_1_6 += 1
                priority = line.priority
                if payment_order.date_prefered == 'due':
                    requested_date = line.ml_maturity_date or today
                elif payment_order.date_prefered == 'fixed':
                    requested_date = payment_order.date_scheduled or today
                else:
                    requested_date = today
                if not line.sdd_mandate_id:
                    raise orm.except_orm(
                        _('Error:'),
                        _("Missing SEPA Direct Debit mandate on the payment "
                            "line with partner '%s' and Invoice ref '%s'.")
                        % (line.partner_id.name,
                            line.ml_inv_ref.number))
                if line.sdd_mandate_id.state != 'valid':
                    raise orm.except_orm(
                        _('Error:'),
                        _("The SEPA Direct Debit mandate with reference '%s' "
                            "for partner '%s' has expired.")
                        % (line.sdd_mandate_id.unique_mandate_reference,
                            line.sdd_mandate_id.partner_id.name))
                if line.sdd_mandate_id.type == 'oneoff':
                    if not line.sdd_mandate_id.last_debit_date:
                        seq_type = 'OOFF'
                    else:
                        raise orm.except_orm(
                            _('Error:'),
                            _("The mandate with reference '%s' for partner "
                                "'%s' has type set to 'One-Off' and it has a "
                                "last debit date set to '%s', so we can't use "
                                "it.")
                            % (line.sdd_mandate_id.unique_mandate_reference,
                                line.sdd_mandate_id.partner_id.name,
                                line.sdd_mandate_id.last_debit_date))
                elif line.sdd_mandate_id.type == 'recurrent':
                    seq_type_map = {
                        'recurring': 'RCUR',
                        'first': 'FRST',
                        'final': 'FNAL',
                        }
                    seq_type_label = \
                        line.sdd_mandate_id.recurrent_sequence_type
                    assert seq_type_label is not False
                    seq_type = seq_type_map[seq_type_label]

                key = (requested_date, priority, seq_type)
                if key in lines_per_group:
                    lines_per_group[key].append(line)
                else:
                    lines_per_group[key] = [line]
                # Write requested_exec_date on 'Payment date' of the pay line
                if requested_date != line.date:
                    self.pool['payment.line'].write(
                        cr, uid, line.id,
                        {'date': requested_date}, context=context)

        for (requested_date, priority, sequence_type), lines in \
                lines_per_group.items():
            # B. Payment info
            payment_info_2_0, nb_of_transactions_2_4, control_sum_2_5 = \
                self.generate_start_payment_info_block(
                    cr, uid, pain_root,
                    "sepa_export.payment_order_ids[0].reference + '-' + "
                    "sequence_type + '-' + requested_date.replace('-', '')  "
                    "+ '-' + priority",
                    priority, 'CORE', sequence_type, requested_date, {
                        'sepa_export': sepa_export,
                        'sequence_type': sequence_type,
                        'priority': priority,
                        'requested_date': requested_date,
                    }, gen_args, context=context)

            self.generate_party_block(
                cr, uid, payment_info_2_0, 'Cdtr', 'B',
                'sepa_export.payment_order_ids[0].mode.bank_id.partner_id.'
                'name',
                'sepa_export.payment_order_ids[0].mode.bank_id.acc_number',
                'sepa_export.payment_order_ids[0].mode.bank_id.bank.bic',
                {'sepa_export': sepa_export},
                gen_args, context=context)

            charge_bearer_2_24 = etree.SubElement(payment_info_2_0, 'ChrgBr')
            charge_bearer_2_24.text = sepa_export.charge_bearer

            creditor_scheme_identification_2_27 = etree.SubElement(
                payment_info_2_0, 'CdtrSchmeId')
            self.generate_creditor_scheme_identification(
                cr, uid, creditor_scheme_identification_2_27,
                'sepa_export.payment_order_ids[0].company_id.'
                'sepa_creditor_identifier',
                'SEPA Creditor Identifier', {'sepa_export': sepa_export},
                'SEPA', gen_args, context=context)

            transactions_count_2_4 = 0
            amount_control_sum_2_5 = 0.0
            for line in lines:
                transactions_count_2_4 += 1
                # C. Direct Debit Transaction Info
                dd_transaction_info_2_28 = etree.SubElement(
                    payment_info_2_0, 'DrctDbtTxInf')
                payment_identification_2_29 = etree.SubElement(
                    dd_transaction_info_2_28, 'PmtId')
                end2end_identification_2_31 = etree.SubElement(
                    payment_identification_2_29, 'EndToEndId')
                end2end_identification_2_31.text = self._prepare_field(
                    cr, uid, 'End to End Identification', 'line.name',
                    {'line': line}, 35,
                    gen_args=gen_args, context=context)
                currency_name = self._prepare_field(
                    cr, uid, 'Currency Code', 'line.currency.name',
                    {'line': line}, 3, gen_args=gen_args,
                    context=context)
                instructed_amount_2_44 = etree.SubElement(
                    dd_transaction_info_2_28, 'InstdAmt', Ccy=currency_name)
                instructed_amount_2_44.text = '%.2f' % line.amount_currency
                amount_control_sum_1_7 += line.amount_currency
                amount_control_sum_2_5 += line.amount_currency
                dd_transaction_2_46 = etree.SubElement(
                    dd_transaction_info_2_28, 'DrctDbtTx')
                mandate_related_info_2_47 = etree.SubElement(
                    dd_transaction_2_46, 'MndtRltdInf')
                mandate_identification_2_48 = etree.SubElement(
                    mandate_related_info_2_47, 'MndtId')
                mandate_identification_2_48.text = self._prepare_field(
                    cr, uid, 'Unique Mandate Reference',
                    'line.sdd_mandate_id.unique_mandate_reference',
                    {'line': line}, 35,
                    gen_args=gen_args, context=context)
                mandate_signature_date_2_49 = etree.SubElement(
                    mandate_related_info_2_47, 'DtOfSgntr')
                mandate_signature_date_2_49.text = self._prepare_field(
                    cr, uid, 'Mandate Signature Date',
                    'line.sdd_mandate_id.signature_date',
                    {'line': line}, 10,
                    gen_args=gen_args, context=context)
                if sequence_type == 'FRST' and (
                        line.sdd_mandate_id.last_debit_date or
                        not line.sdd_mandate_id.sepa_migrated):
                    previous_bank = self._get_previous_bank(
                        cr, uid, line, context=context)
                    if previous_bank or not line.sdd_mandate_id.sepa_migrated:
                        amendment_indicator_2_50 = etree.SubElement(
                            mandate_related_info_2_47, 'AmdmntInd')
                        amendment_indicator_2_50.text = 'true'
                        amendment_info_details_2_51 = etree.SubElement(
                            mandate_related_info_2_47, 'AmdmntInfDtls')
                    if previous_bank:
                        if previous_bank.bank.bic == line.bank_id.bank.bic:
                            ori_debtor_account_2_57 = etree.SubElement(
                                amendment_info_details_2_51, 'OrgnlDbtrAcct')
                            ori_debtor_account_id = etree.SubElement(
                                ori_debtor_account_2_57, 'Id')
                            ori_debtor_account_iban = etree.SubElement(
                                ori_debtor_account_id, 'IBAN')
                            ori_debtor_account_iban.text = self._validate_iban(
                                cr, uid, self._prepare_field(
                                    cr, uid, 'Original Debtor Account',
                                    'previous_bank.acc_number',
                                    {'previous_bank': previous_bank},
                                    gen_args=gen_args,
                                    context=context),
                                context=context)
                        else:
                            ori_debtor_agent_2_58 = etree.SubElement(
                                amendment_info_details_2_51, 'OrgnlDbtrAgt')
                            ori_debtor_agent_institution = etree.SubElement(
                                ori_debtor_agent_2_58, 'FinInstnId')
                            ori_debtor_agent_bic = etree.SubElement(
                                ori_debtor_agent_institution, bic_xml_tag)
                            ori_debtor_agent_bic.text = self._prepare_field(
                                cr, uid, 'Original Debtor Agent',
                                'previous_bank.bank.bic',
                                {'previous_bank': previous_bank},
                                gen_args=gen_args,
                                context=context)
                            ori_debtor_agent_other = etree.SubElement(
                                ori_debtor_agent_institution, 'Othr')
                            ori_debtor_agent_other_id = etree.SubElement(
                                ori_debtor_agent_other, 'Id')
                            ori_debtor_agent_other_id.text = 'SMNDA'
                            # SMNDA = Same Mandate New Debtor Agent
                    elif not line.sdd_mandate_id.sepa_migrated:
                        ori_mandate_identification_2_52 = etree.SubElement(
                            amendment_info_details_2_51, 'OrgnlMndtId')
                        ori_mandate_identification_2_52.text = \
                            self._prepare_field(
                                cr, uid, 'Original Mandate Identification',
                                'line.sdd_mandate_id.'
                                'original_mandate_identification',
                                {'line': line},
                                gen_args=gen_args,
                                context=context)
                        ori_creditor_scheme_id_2_53 = etree.SubElement(
                            amendment_info_details_2_51, 'OrgnlCdtrSchmeId')
                        self.generate_creditor_scheme_identification(
                            cr, uid, ori_creditor_scheme_id_2_53,
                            'sepa_export.payment_order_ids[0].company_id.'
                            'original_creditor_identifier',
                            'Original Creditor Identifier',
                            {'sepa_export': sepa_export},
                            'SEPA', gen_args, context=context)

                self.generate_party_block(
                    cr, uid, dd_transaction_info_2_28, 'Dbtr', 'C',
                    'line.partner_id.name',
                    'line.bank_id.acc_number',
                    'line.bank_id.bank.bic',
                    {'line': line}, gen_args, context=context)

                self.generate_remittance_info_block(
                    cr, uid, dd_transaction_info_2_28,
                    line, gen_args, context=context)

            nb_of_transactions_2_4.text = str(transactions_count_2_4)
            control_sum_2_5.text = '%.2f' % amount_control_sum_2_5
        nb_of_transactions_1_6.text = str(transactions_count_1_6)
        control_sum_1_7.text = '%.2f' % amount_control_sum_1_7

        return self.finalize_sepa_file_creation(
            cr, uid, ids, xml_root, total_amount, transactions_count_1_6,
            gen_args, context=context)

    def cancel_sepa(self, cr, uid, ids, context=None):
        '''
        Cancel the SEPA file: just drop the file
        '''
        sepa_export = self.browse(cr, uid, ids[0], context=context)
        self.pool.get('banking.export.sdd').unlink(
            cr, uid, sepa_export.file_id.id, context=context)
        return {'type': 'ir.actions.act_window_close'}

    def save_sepa(self, cr, uid, ids, context=None):
        """
        Aanpassing nav traagheid en idee van natuurpunt/fabian

         1. Write state sent
         2. move 1 aanmaken & link opslaan in payment order, als deze nog niet bestaat (!)  -> sdd_move_id
         3. per betaal regel:
            4. too expire,, first mandate ids opslaan
            5. validate_crm_payment, per invoice!
            6. Add booking to 1e booking
            7. *COMMIT*
         8. post move 1
         9. total amount new + rcur voor move 2 opbouwen
            (Kan, want nieuwe mandate status nog niet geschreven)
        10. make & post move 2
        11. flag ssd payment requested on the invoice
        12. nieuwe status mandate_ids wegschrijven
        13. Workflow state to done
        return, and commit to database
        """
        if context is None: context = {}

        mv_obj = self.pool.get('account.move')

        sepa_export = self.browse(cr, uid, ids[0], context=context)
        LOGGER.info('sepa_export context:' + str(context))

        # Stap 1
        self.pool.get('banking.export.sdd').write(
            cr, uid, sepa_export.file_id.id, {'state': 'sent'},
            context=context)
        wf_service = netsvc.LocalService('workflow')
        for order in sepa_export.payment_order_ids:
            to_expire_ids = []
            first_mandate_ids = []

            mandate_ids = [line.sdd_mandate_id.id for line in order.line_ids]
            old_mandate_info = {}
            Mandateinformation = collections.namedtuple('Mandateinformation', 'mandate_id mandate_type partner_id line_id')

            for line in order.line_ids:
                old_mandate_info[line.partner_id.id] = Mandateinformation(
                    mandate_id=line.sdd_mandate_id.id,
                    mandate_type=line.sdd_mandate_id.recurrent_sequence_type,
                    partner_id=line.sdd_mandate_id.partner_id.id,
                    line_id=line.id, )

            line_nbr = len(order.line_ids)

            if not order.sdd_move_id:
                # If we do not have a ssd move, create one.
                sdd_move_id = self._create_batch_booking(cr, uid, order, context=context)
                LOGGER.info("New sdd_move_id id %s" % (sdd_move_id,))
            else:
                sdd_move_id = order.sdd_move_id.id
                LOGGER.info("sdd_move_id already in database: id: %s, reference: %s" % (sdd_move_id, order.sdd_move_id.ref,))
            # cr.commit()
            # We have created the ordermove, reload order
            order = self.pool.get('payment.order').browse(cr, uid, order.id, context=context)
            # Stap 4 - To expire mandaad id's opslaan
            amount_first = 0.0
            amount_rcur = 0.0
            total_amount = 0.0
            for line in order.line_ids:
                total_amount += line.amount_currency
                if line.sdd_mandate_id.type == 'oneoff':
                    to_expire_ids.append(line.sdd_mandate_id.id)
                    amount_rcur += line.amount_currency
                elif line.sdd_mandate_id.type == 'recurrent':
                    seq_type = line.sdd_mandate_id.recurrent_sequence_type
                    if seq_type == 'final':
                        amount_rcur += line.amount_currency
                        to_expire_ids.append(line.sdd_mandate_id.id)
                    elif seq_type == 'first':
                        amount_first += line.amount_currency
                        first_mandate_ids.append(line.sdd_mandate_id.id)
                    elif seq_type == 'recurring':
                        amount_rcur += line.amount_currency

                # Stap 5 - validate_crm_payment per invoice
                if line.ml_inv_ref:
                    LOGGER.info("invoice %s status: %s" % (line.ml_inv_ref.number, line.ml_inv_ref.state))
                    if line.ml_inv_ref.state == 'open':
                        # Stap 5 - validate_crm_payment, per invoice!
                        # Doet ook Stap 6, add booking to sdd_move_id
                        inv = self.pool.get('account.invoice').validate_crm_payment(cr, uid, [line.ml_inv_ref.id], order, context=context)
                    else:
                        LOGGER.info('Invoice %s is already paid' % (line.ml_inv_ref.number,))
                    line_nbr -= 1
                    # Stap 7 -- *commit* to database so we can restart in case of errors
                    cr.commit()

                    LOGGER.info('Direct Debit Order %s invoice preocessed : %s' % (order.id, line.ml_inv_ref.number))
                LOGGER.info('Direct Debit Order %s lines left to process : %s' % (order.id, line_nbr))
            if line_nbr >= 1:
                raise osv.except_osv(_('Error!'), _('There are errors in this payment batch'))

            # If everything is alright, validate!
            # World! The time has come to push the button.
            # Push the validate Button!
            # mv_obj.button_validate(cr, uid, [order.sdd_move_id.id], context=context)
            # Of niet, want we willen alles in concept houden.. :)

            # Stap 9, create moves for first and rcurring mandates
            # Store amount for booking from paymant journal to new journal

            if total_amount != (amount_first + amount_rcur):
                raise orm.except_orm(
                    _('Error:'),
                    "Totale bedrag (%d), komt niet overeen met currurring (%d) en first (%d) bedrag!" % (
                        total_amount, amount_rcur, amount_first))
            if total_amount != order.total:
                    raise orm.except_orm(
                    _('Error:'),
                    "Totale bedrag (%d), komt niet overeen met order total (%d)!" % (
                        total_amount, order.total))

            context['journal_id'] = order.mode.transfer_journal_id.id
            context['sale_order_reference'] = order.reference
            invoice_ids = []
            for lines in order.line_ids:
                if lines.ml_inv_ref:
                    invoice_ids.append(lines.ml_inv_ref.id)

            # After the validated invoices, create two new bookings to the incasso debit account and journal
            LOGGER.info("Creating move for first amount: %s" % (amount_first,))
            if amount_first > 0.0:
                debit_move_first = self.create_debit_move(cr, uid, order, amount_first, "FRST", context=context)
                LOGGER.info("move voor first %s" % (debit_move_first,))
                result = self.createreconcile(cr, uid, order, debit_move_first, sdd_move_id, old_mandate_info, type="FRST", context=context)
                self.pool.get('payment.order').write(cr, uid, order.id, {'first_move_id': debit_move_first}, context=context)

            LOGGER.info("Creating move for recurring amount: %s" % (amount_rcur,))
            if amount_rcur > 0.0:
                debit_move_rcur = self.create_debit_move(cr, uid, order, amount_rcur, "RCUR", context=context)
                LOGGER.info("move voor rcur %s" % (debit_move_rcur,))
                result = self.createreconcile(cr, uid, order, debit_move_rcur, sdd_move_id, old_mandate_info, type="RCUR", context=context)
                self.pool.get('payment.order').write(cr, uid, order.id, {'rcur_move_id': debit_move_rcur}, context=context)


            #Set the flag ssd payment requested on the invoice
            move_ids = []
            for line in order.line_ids:
                move_ids.append(line.move_line_id.move_id.id)
            invoice_ids = self.pool.get('account.invoice').search(cr, uid, [('move_id','in',move_ids)])
            print "invoice_ids:",invoice_ids
            self.pool.get('account.invoice').write(cr, uid, invoice_ids, {'sdd_payment_sent':True})

            self.pool['sdd.mandate'].write(cr, uid, to_expire_ids, {'state': 'expired'}, context=context)
            self.pool['sdd.mandate'].write(cr, uid, first_mandate_ids,
                                           {'recurrent_sequence_type': 'recurring', 'sepa_migrated': True, },
                                           context=context)
            mandate_ids = [line.sdd_mandate_id.id for line in order.line_ids]
            self.pool['sdd.mandate'].write(
                cr, uid, mandate_ids,
                {'last_debit_date': datetime.today().strftime('%Y-%m-%d')},
                context=context)
            wf_service.trg_validate(uid, 'payment.order', order.id, 'done', cr)

            LOGGER.info('Direct Debit Order %s processed' % (order.id,))


        # raise "Ik wil nog neit committen error :)"

        return {'type': 'ir.actions.act_window_close'}

    def _create_batch_booking(self, cr, uid, order, context=None):
        move_pool = self.pool.get('account.move')
        local_ctx = dict(context or {}, account_period_prefer_normal=True)
        seq_obj = self.pool.get('ir.sequence')

        context['journal_id'] = order.mode.debit_journal_id.id

        date_sent = order.date_created
        period_id = self.pool.get('account.period').find(cr, uid, dt=date_sent, context=local_ctx)

        if len(period_id) != 1:
            raise osv.except_osv(_('Configuration Error !'), _('More then one period found for this date'))

        period_id = period_id[0]
        period_obj = self.pool.get('account.period').browse(cr, uid, period_id, context=local_ctx)

        if order.mode.transfer_journal_id.sequence_id:
            if not order.mode.debit_journal_id.sequence_id.active:
                raise osv.except_osv(_('Configuration Error !'),
                                     _('Please activate the sequence of selected journal !'))
            c = dict(context)
            c.update({'fiscalyear_id': period_obj.fiscalyear_id.id})
            name = seq_obj.next_by_id(cr, uid, order.mode.debit_journal_id.sequence_id.id, context=c)
        else:
            raise osv.except_osv(_('Error!'),
                                 _('Please define a sequence on the journal.'))
        mv_vals = {
            'journal_id': order.mode.transfer_journal_id.id,
            'date': order.date_created,
            'company_id': order.company_id.id,
            'ref': order.reference,
            'period_id': period_id,
        }

        move_id = move_pool.create(cr, uid, mv_vals, context=context)
        self.pool.get('payment.order').write(cr, uid, order.id, {'sdd_move_id': move_id}, context=context)

        return move_id

    def create_debit_move(self, cr, uid, order, amount, postfix = "", context=None):
        """
         Create debit move from Overschrijf rekening to incaso debit account
        """
        if context is None:
            context = {}
        local_ctx = dict(context or {}, account_period_prefer_normal=True)
        move_pool = self.pool.get('account.move')
        seq_obj = self.pool.get('ir.sequence')

        date_sent = order.date_created

        period_id = self.pool.get('account.period').find(cr, uid, dt=date_sent, context=local_ctx)

        if len(period_id) != 1:
            raise osv.except_osv(_('Configuration Error !'), _('More then one period found for this date'))

        period_id = period_id[0]
        period_obj = self.pool.get('account.period').browse(cr, uid, period_id, context=local_ctx)

        if order.mode.debit_journal_id.sequence_id:
            if not order.mode.debit_journal_id.sequence_id.active:
                raise osv.except_osv(_('Configuration Error !'),
                                     _('Please activate the sequence of selected journal !'))

            c = dict(context)
            c.update({'fiscalyear_id': period_obj.fiscalyear_id.id})
            name = seq_obj.next_by_id(cr, uid, order.mode.debit_journal_id.sequence_id.id, context=c)
        else:
            raise osv.except_osv(_('Error!'),
                                 _('Please define a sequence on the journal.'))

        ref = order.reference + "-" + postfix + '-' +  order.line_ids[0].date.replace('-', '') + '-' + order.line_ids[0].priority

        lines = [
            {
                'name': "Incasso boeking: " + ref,
                'quantity': 1,
                'account_id': order.mode.debit_account_id.id,
                'ref': ref,
                'date': date_sent,
                'debit': amount,
            },
            {
                'name': "Incasso boeking: " + ref,
                'quantity': 1,
                'account_id': order.mode.transfer_account_id.id,
                'ref': ref,
                'date': date_sent,
                'credit': amount,
            }
        ]

        move = {
            'name': name,
            'journal_id': order.mode.debit_journal_id.id,
            'date': date_sent,
            'ref': ref,
            'period_id': period_id,
            'line_id': [(0, 0, line) for line in lines],
        }
        move_id = move_pool.create(cr, uid, move, context=context)
        return move_id

    def createreconcile(self, cr, uid, order, credit_move_line_id, debit_move_line_id, old_mandate_info, type, context=None):
        """
            En nu het afletteren van de regels uit bovenstaande move's:
            We hebben nu één OF twee boekingen van 1420 Incasso's onderweg naar 1305 Incasso's te ontvangen
            In deze boeking zit een dus een regel van 1420, en een regel naar 1305
            De credit regel van 1420 is af te letteren tegenover te losse boekingsregels op 1420
            Maar, moeten wel gesplist worden op new en rcur.
            Deze splitsing kunnen we uit old_mandate_info halen

            :type RCUR of FRST
        """
        if context is None:
            context = {}
        move_line_pool = self.pool.get('account.move.line')
        move_pool = self.pool.get('account.move')

        # Credit boeking
        move_line_credit_ids = move_line_pool.search(cr, uid, [('move_id', '=', credit_move_line_id), ('account_id', '=', order.mode.transfer_account_id.id)], context=context)

        # Debit boekingen, dus alle boekingsregels van deze move van type
        move_line_debit_ids = move_line_pool.search(cr, uid, [('move_id', '=', debit_move_line_id), ('account_id', '=', order.mode.transfer_account_id.id)], context=context)
        move_lines_debit = move_line_pool.browse(cr, uid, move_line_debit_ids, context=context)

        found_move_lines_debit = []
        for move_line in move_lines_debit:
            if type == "FRST" and old_mandate_info[move_line.partner_id.id].mandate_type == "first":
                found_move_lines_debit.append(move_line.id)
            elif type == "RCUR" and old_mandate_info[move_line.partner_id.id].mandate_type == "recurring":
                found_move_lines_debit.append(move_line.id)

        rec_ids = move_line_credit_ids + found_move_lines_debit
        reconcile = move_line_pool.reconcile(cr, uid, rec_ids, context=context)

        return reconcile
