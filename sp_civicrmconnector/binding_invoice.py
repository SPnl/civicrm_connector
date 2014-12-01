# -*- coding: utf-8 -*-

from openerp.osv import fields, orm
from openerp.addons.connector.event import on_record_write
from openerp.addons.connector.event import on_record_create
from openerp.addons.connector.event import on_record_unlink
# from .unit.export_synchronizer import export_record
from connector import get_environment
from openerp.addons.connector.connector import ConnectorUnit
from openerp.addons.connector.unit.synchronizer import ExportSynchronizer
from backend import civicrm
from openerp.addons.connector.connector import Binder
from datetime import datetime
from openerp.tools import DEFAULT_SERVER_DATETIME_FORMAT
from openerp.addons.connector.queue.job import job
from binder import CivicrmBinder
from binding import CiviCRMExportSynchronizer

from civicrm import Civicrm
from pythoncivicrm import *
import pprint

class civicrm_acount_invoice(orm.Model):
    _inherit = 'account.invoice'
    _columns = {
        'backend_id': fields.many2one('civicrm.backend', 'Civicrm Backend', ondelete='restrict'),
        'civicrm_id': fields.integer('ID on Civicrm'),
        'sync_date': fields.datetime('Last synchronization date'),
        'betalingsregeling': fields.boolean('Betalingsregeling op deze factuur'),
    }

    def _get_backend(self, cr, uid, context=None):
        comp = self.pool.get('res.users').browse(cr, uid, uid).company_id
        if not comp:
            comp_id = self.pool.get('res.company').search(cr, uid, [])[0]
            comp = self.pool.get('res.company').browse(cr, uid, comp_id)
        return comp.backend_id.id

    _defaults = {
        'backend_id': _get_backend,
    }

@on_record_write(model_names=['account.invoice'])
def delay_export_account_invoice_write(session, model_name, record_id, vals):
    print "In delay_export_account_invoice_write"
    print "session", session
    print "model_name", model_name
    print "record_id", record_id
    print "fields", vals
    if 'state' in vals:
        # We are editing state
        export_account_invoice_write.delay(session, model_name, record_id, vals)

@job
def export_account_invoice_write(session, model_name, record_id, vals):
    print "in export_account_invoice_write"

    account_invoice = session.browse(model_name, record_id)
    backend_id = account_invoice.backend_id.id
    env = get_environment(session, model_name, backend_id)
    account_invoice_updater = env.get_connector_unit(CiviCRMInvoiceUpdater)
    return account_invoice_updater.run(record_id, vals)

@on_record_create(model_names=['account.invoice'])
def delay_export_account_invoice_create(session, model_name, record_id, vals):
    print "In delay_export_account_invoice_write"
    print "session", session
    print "model_name", model_name
    print "record_id", record_id
    print "fields", vals
    if 'state' in vals:
        # We are editing state
        export_account_invoice_create.delay(session, model_name, record_id, vals)

@job
def export_account_invoice_create(session, model_name, record_id, vals):
    print "in export_account_invoice_create"

    account_invoice = session.browse(model_name, record_id)
    backend_id = account_invoice.backend_id.id
    env = get_environment(session, model_name, backend_id)
    partner_location_exporter = env.get_connector_unit(CiviCRMInvoiceCreator)
    return partner_location_exporter.run(record_id, vals)



@civicrm
class CiviCRMInvoiceUpdater(CiviCRMExportSynchronizer):
    """ Export partners to civicrm """
    _model_name = ['account.invoice']

    def run(self, binding_id, vals):
        print "We are in run", binding_id
        print "en vals", vals
        pass

@civicrm
class CiviCRMInvoiceCreator(CiviCRMExportSynchronizer):
    """ Export partners to civicrm """
    _model_name = ['account.invoice']

    def run(self, binding_id, vals):
        print "We are in run", binding_id
        print "en vals", vals
        pass
