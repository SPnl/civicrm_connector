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
import time
import pprint

class civicrm_res_partner(orm.Model):
    _inherit = 'res.partner'

    def get_civicrm_link(self, cr, uid, ids, context=None):
        """
        Generate link to civicrm
        """
        partners = self.browse(cr, uid, ids, context=context)
        for rec in partners:
            url = "https://dev.civicrm.sp.nl/civicrm/contact/view?reset=1&cid=" + str(rec.civicrm_id)
            action = {
                'type': 'ir.actions.act_url',
                'target': 'new',
                'url': url,
            }
            return action

    _columns = {
        'civicrm_id': fields.integer('ID on Civicrm'),
    }
    _sql_constraints = [
        ('civicrm_id_uniq', 'unique(civicrm_id)', 'The civicrm ID must be unique.')
    ]

class civicrm_res_partner_position(orm.Model):
    _inherit = 'res.partner.position'


    _columns = {
        'backend_id': fields.many2one('civicrm.backend', 'Civicrm Backend', ondelete='restrict'),
        'civicrm_id': fields.integer('ID on Civicrm'),
        'sync_date': fields.datetime('Last synchronization date'),
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


class res_partner_position_appointment(orm.Model):
    _inherit = 'res.partner.position.appointment'
    _civiCRMType = (
        ('sprel_fractievoorzitter_afdeling', 'is fractievoorzitter van', 'SP_Afdeling'),
        ('sprel_fractievoorzitter_provincie', 'is fractievoorzitter van', 'SP_Provincie'),
        ('sprel_fractievoorzitter_landelijk', 'is fractievoorzitter van', 'SP_Landelijk'),
        ('sprel_fractieraadslid_afdeling', 'is fractieraadslid van', 'SP_Afdeling', 'SP-Afdeling'),
        ('sprel_deelraadslid_afdeling', 'is deelraadslid van', 'SP_Afdeling'),
        ('sprel_wethouder_afdeling', 'is wethouder van', 'SP_Afdeling'),
        ('sprel_statenlid_provincie', 'is statenlid van', 'SP_Provincie'),
        ('sprel_gedeputeerde_provincie', 'is gedeputeerde van', 'SP_Provincie'),
        ('sprel_tweede_kamerlid_landelijk', 'is tweede-kamerlid van', 'SP_Landelijk'),
        ('sprel_eerste_kamerlid_landelijk', 'is eerste-kamerlid van', 'SP_Landelijk'),
        ('sprel_europarlementarier_landelijk', 'is europarlementariër van', 'SP_Landelijk'),
        ('sprel_regiobestuurder_landelijk', 'is regiobestuurder van', 'SP_Regio'),

    )

    def getcivilocationtype(self, cr, uid, record, search, context=None, *args, **kwargs):
        for item in self._civiCRMType:
            if search == item[0]:
                return item[2]
        raise KeyError('Type not found in civiCRMTypes')

    def getcivilocationprefix(self, cr, uid, record, search, context=None):
        for item in self._civiCRMType:
            if search == item[0] and len(item) >= 4:
                return item[3]
        return False
        

    def _get_selection(self, cursor, user_id, context=None):
        allItems = []
        for civitype in self._civiCRMType:
            allItems.append(civitype[:2])

        return allItems

    _columns = {
        'civicrm_relationshiptype': fields.selection(_get_selection, 'RelationshipType', help="Deze optie bepaald het type RelationshipType/Relatietypes binnen CiviCRM"),
        'civicrm_relation': fields.char('CiviCRM Location', help="Als deze ingesteld is, Forceer het koppelen met deze relatie. Bijvoobeeld 2e kamer met SP Bedrijf" ),
    }


@on_record_create(model_names='res.partner.position')
def delay_export_res_partner_location(session, model_name, record_id, fields=None):
    """
    Delay the job to export the delay_export_res_partner_location.
    """
    export_res_partner_position.delay(session, model_name, record_id)

@job
def export_res_partner_position(session, model_name, record_id):
    """ Export a new partner position to civicrm """
    if session.context.get('connector_no_export'):
        return

    partner_position = session.browse(model_name, record_id)
    backend_id = partner_position.backend_id.id
    env = get_environment(session, model_name, backend_id)
    partner_location_exporter = env.get_connector_unit(CiviCRMLocationSynchronizer)
    return partner_location_exporter.run(record_id)

@on_record_write(model_names=['res.partner.position'])
def delay_export_res_partner_location_write(session, model_name, record_id, vals):
    export_res_partner_position_write.delay(session, model_name, record_id, vals)

@job
def export_res_partner_position_write(session, model_name, record_id, vals):
    partner_position = session.browse(model_name, record_id)
    backend_id = partner_position.backend_id.id
    env = get_environment(session, model_name, backend_id)
    partner_location_exporter = env.get_connector_unit(CiviCRMLocationUpdater)
    return partner_location_exporter.run(record_id, vals)


@civicrm
class CiviCRMLocationUpdater(CiviCRMExportSynchronizer):
    """ Export partners to civicrm """
    _model_name = ['res.partner.position']
    def run(self, binding_id, vals):
        """ Run the job to export the validated/paid invoice """
        sess = self.session
        position = sess.browse(self.model._name, binding_id)
        backend = position.backend_id
        civicrmconnector = CiviCRM(backend.url, backend.site_key, backend.api_key)

        params = {}
        for val in vals:
            if val == 'start_date':
                params['start_date'] = self._makecivitime(vals[val])

            elif val == 'stop_date':
                params['end_date'] = self._makecivitime(vals[val])

        if len(params) == 0:
            return
        result = civicrmconnector.update('Relationship', db_id=position.civicrm_id, **params)
        self.binder.bind(result[0]['id'], binding_id)


@civicrm
class CiviCRMLocationSynchronizer(CiviCRMExportSynchronizer):
    """ Export partners to civicrm """
    _model_name = ['res.partner.position']

    def run(self, binding_id):
        """ Run the job to export the validated/paid invoice """
        sess = self.session
        position = sess.browse(self.model._name, binding_id)

        backend = position.backend_id
        civicrmconnector = CiviCRM(backend.url, backend.site_key, backend.api_key)
        # Civi ID zoeken:
        if position.partner_id.civicrm_id == 0:
            raise ValueError('The contact %s (%s) has no civicrm_id' % (position.partner_id.name,position.partner_id))

        person = civicrmconnector.getsingle('Contact', id=position.partner_id.civicrm_id)

        if position.appointment_id.civicrm_relation:
            civicrm_relation = position.appointment_id.civicrm_relation
        else:
            if not position.appointment_id.location_type_id:
                raise ValueError('The concact %s (%s) has no Location' % (position.partner_id.name, position.partner_id))
            else:
                prefix = position.appointment_id.getcivilocationprefix(position.appointment_id.civicrm_relationshiptype)
                if prefix:
                    civicrm_relation = prefix + " " + position.location_id.name
                else:
                    civicrm_relation = position.location_id.name

        subtype_b = position.appointment_id.getcivilocationtype(position.appointment_id.civicrm_relationshiptype)
        str_relation = str(civicrm_relation)
        contact_b = civicrmconnector.getsingle('Contact', contact_sub_type=subtype_b, organization_name=str_relation)

        # Relationship id:
        relationtype = civicrmconnector.getsingle('RelationshipType', name_a_b=position.appointment_id.civicrm_relationshiptype)

        params = {
            'relationship_type_id': relationtype['id'],
            'contact_id_a': person['id'],
            'contact_id_b': contact_b['id'],
        }
        if position.start_date:
            params['start_date'] = self._makecivitime(position.start_date)

        if position.stop_date:
            params['stop_date'] = self._makecivitime(position.stop_date)

        result = civicrmconnector.create('Relationship', **params)

        # use the ``binder`` to write the external ID
        self.binder.bind(result[0]['id'], binding_id)
