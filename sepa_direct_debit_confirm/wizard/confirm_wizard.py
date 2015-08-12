# -*- encoding: utf-8 -*-
##############################################################################
#
#    SEPA Direct Debit Bactch confirm with connector module
#    Copyright (C) 2015 B-informed
#    @author: Roel Adriaans <roel.adriaans@b-informed.nl>
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

import pooler
from openerp.osv import fields, orm

from openerp.addons.connector.session import ConnectorSession
from openerp.addons.connector.queue.job import job


class wizard_partner_donation(orm.TransientModel):
    _name = 'wizard.direct.debit.confirm'
    _columns = {
        'action': fields.selection([
            ('mark', 'Mark for processing'),
            ('unmark', 'Unmark for processing'),
        ], "Action", required=True),
        'eta': fields.integer('Seconds to wait before starting the jobs'),
        'payment_ids': fields.many2many('payment.order', string='Payment orders to process'),
    }

    def _get_payment_ids(self, cr, uid, context=None):
        if context is None:
            context = {}
        res = False
        if context.get('active_model') == 'payment.order' and context.get('active_ids'):
            res = context['active_ids']
        return res

    _defaults = {
        'action': 'mark',
        'eta': 0,
        'payment_ids': _get_payment_ids,
    }

    def button_mark(self, cr, uid, ids, context=None):
        """Create a single job that will create one job per payment order.

        Return action.

        """
        session = ConnectorSession(cr, uid, context=context)
        for wizard_id in ids:
            # to find out what _classic_write does, read the documentation.
            wizard_data = self.read(cr, uid, wizard_id, context=context, load='_classic_write')
            wizard_data.pop('id')
            active_ids = context['active_ids']
            if context.get('automated_test_execute_now'):
                process_wizard(session, self._name, wizard_data)
            else:
                process_wizard.delay(session, self._name, wizard_data)

        return {'type': 'ir.actions.act_window_close'}

    def process_wizard(self, cr, uid, ids, context=None):
        """Choose the correct list of payment orders to mark and then validate."""
        for wiz in self.browse(cr, uid, ids, context=context):

            payment_obj = self.pool['payment.order']
            payment_ids = [x.id for x in wiz.payment_ids]

            if wiz.action == 'mark':
                payment_obj.mark_for_processing(cr, uid, payment_ids, eta=wiz.eta, context=context)

            elif wiz.action == 'unmark':
                payment_obj.unmark_for_processing(cr, uid, payment_ids, context=context)

@job
def process_wizard(session, model_name, wizard_data):
    """Create jobs to process payment orders."""

    wiz_obj = session.pool[model_name]

    # Convert payment ids from wizard_data to orm add lines
    wizard_data['payment_ids'] = [(6, 0, wizard_data['payment_ids'])]
    new_wiz_id = wiz_obj.create(
        session.cr,
        session.uid,
        wizard_data,
        session.context
    )

    wiz_obj.process_wizard(
        session.cr,
        session.uid,
        ids=[new_wiz_id],
        context=session.context,
    )
