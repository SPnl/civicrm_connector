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
"""Accounting customisation for delayed processing."""

import logging

from openerp.osv import fields, orm
from openerp.tools.translate import _
from openerp import netsvc, pooler

from openerp.addons.connector.queue.job import job
from openerp.addons.connector.session import ConnectorSession
from openerp.addons.connector.queue.job import OpenERPJobStorage

_logger = logging.getLogger(__name__)

# do a massive write on supplier pricelists BLOCK_SIZE at a time
# This used to be 1000, but we have a few large items, and not alot of small items like account.move
BLOCK_SIZE = 5


class PaymentOrder(orm.Model):
    """We modify the payment.order to allow delayed processing."""

    _inherit = 'payment.order'

    _columns = {
        'to_process': fields.boolean(
            'Processing Requested',
            readonly=True,
            help='Check this box to mark the payment.order for batch processing'
        ),
        'post_job_uuid': fields.char(
            'UUID of the Job to approve this move'
        ),
    }

    def _delay_paymentorder_marked(self, cr, uid, eta=None, paymentorder_ids=None, context=None):
        """Create a job for every payment order marked for batch processing.

        If some payment.orders already have a job, they are skipped.
        """
        if context is None:
            context = {}
        if paymentorder_ids is None:
            paymentorder_ids = []

        session = ConnectorSession(cr, uid, context=context)
        name = self._name

        # maybe not creating too many dictionaries will make us a bit faster
        values = {'post_job_uuid': None}
        _logger.info(
            u'{0} jobs for processing payment orders have been created.'.format(
                len(paymentorder_ids)
            )
        )

        for paymentorder_id in paymentorder_ids:
            job_uuid = validate_one_payment_order.delay(session, name, paymentorder_id, eta=eta)
            values['post_job_uuid'] = job_uuid
            self.write(cr, uid, [paymentorder_id], values)
            cr.commit()

    def _cancel_jobs(self, cr, uid, context=None):
        """Find payment.orders where the mark has been removed and cancel the jobs.
        """

        if context is None:
            context = {}

        session = ConnectorSession(cr, uid, context=context)
        storage = OpenERPJobStorage(session)

        paymentorder_ids = self.search(cr, uid, [
            ('to_process', '=', False),
            ('post_job_uuid', '!=', False)
        ], context=context)

        for paymentorder in self.browse(cr, uid, paymentorder_ids, context=context):
            job_rec = storage.load(paymentorder.post_job_uuid)
            if job_rec.state in (u'pending', u'enqueued'):
                job_rec.set_done(result=_(
                    u'Task set to Done because the user unmarked the payment order'
                ))
                storage.store(job_rec)

    def mark_for_processing(self, cr, uid, payment_ids, eta=None, context=None):
        """Mark a list of payment orders for delayed processing, and enqueue the jobs."""
        if context is None:
            context = {}
        # For massive amounts of payment orders, this becomes necessary to avoid MemoryError's

        _logger.info(
            u'{0} payment orders marked for processing.'.format(len(payment_ids))
        )

        for start in xrange(0, len(payment_ids), BLOCK_SIZE):
            self.write(
                cr,
                uid,
                payment_ids[start:start + BLOCK_SIZE],
                {'to_process': True},
                context=context)
            # users like to see the flag sooner rather than later
            cr.commit()
        self._delay_paymentorder_marked(cr, uid, eta=eta, paymentorder_ids=payment_ids, context=context)

    def unmark_for_processing(self, cr, uid, payment_ids, context=None):
        """Unmark payment orders for delayed processing, and cancel the jobs."""
        if context is None:
            context = {}
        self.write(cr, uid, payment_ids, {'to_process': False}, context=context)
        self._cancel_jobs(cr, uid, context=context)


@job
def validate_one_payment_order(session, model_name, paymentorder_id):
    """Process a payment_order, and leave the job reference in place."""
    paymentorder_pool = session.pool['payment.order']
    wf_service = netsvc.LocalService("workflow")

    if paymentorder_pool.exists(session.cr, session.uid, [paymentorder_id]):
        payment_order = paymentorder_pool.browse(session.cr, session.uid, paymentorder_id)
        if payment_order['state'] == 'done':
            return _(u'Payment order already processed')

        if payment_order['state'] == 'draft':
            _logger.info(u'payment order with id {0} still in draft, confirming first'.format(paymentorder_id))
            # result = sock.exec_workflow(dbname, uid, pwd, model, 'open', payment_order_id, context)
            wf_service.trg_validate(session.uid, 'payment.order', paymentorder_id, 'open', session.cr)
            _logger.info(u'payment order with id {0} set to open'.format(paymentorder_id))

        # now, create a wizard
        wiz_obj = session.pool['banking.export.sdd.wizard']
        wizard_data = {
            'batch_booking': True,
            'charge_bearer': 'SLEV',
        }

        wizard_context = session.context.copy()
        wizard_context.update({
               'uid': session.uid,
               'active_model': 'payment.order',
               'search_disable_custom_filters': True,
               'active_ids': [paymentorder_id, ],
               'active_id': paymentorder_id,

        })

        wiz_id = wiz_obj.create(session.cr, session.uid, wizard_data, wizard_context)

        _logger.info(u'Created new banking.export.sdd.wizard with id {0}, creating sepa order with id {1}.'.format(wiz_id, paymentorder_id))

        res = wiz_obj.create_sepa(session.cr, session.uid, [wiz_id])

        _logger.info(u'Payment order with id {0} has created as sepa file'.format(paymentorder_id))

        wiz_obj.save_sepa(session.cr, session.uid, [wiz_id])

        _logger.info(u'Payment order with id {0} has been saved as sepa'.format(paymentorder_id))
    else:
        return _(u'Nothing to do because the record has been deleted')
