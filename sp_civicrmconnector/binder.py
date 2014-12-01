from datetime import datetime
from openerp.tools import DEFAULT_SERVER_DATETIME_FORMAT
from openerp.addons.connector.connector import Binder
from backend import civicrm


@civicrm
class CivicrmBinder(Binder):
    _model_name = ['res.partner.position', 'account.invoice']
    # To openerp nog niet getest en/f nodig gehad.
    def to_openerp(self, external_id, unwrap=False):
        """ Give the OpenERP ID for an external ID

        :param external_id: external ID for which we want the OpenERP ID
        :param unwrap: if True, returns the openerp_id of the icops_xxxx
        record, else return the id (binding id) of that record
        :return: a record ID, depending on the value of unwrap,
                 or None if the external_id is not mapped
        :rtype: int
        """
        binding_ids = self.session.search(
            self.model._name,
            [('civicrm_id', '=', external_id),
             ('backend_id', '=', self.backend_record.id)])
        if not binding_ids:
            return None
        assert len(binding_ids) == 1, "Several records found: %s" % binding_ids
        binding_id = binding_ids[0]
        if unwrap:
            return self.session.read(self.model._name,
                                     binding_id,
                                     ['openerp_id'])['openerp_id'][0]
        else:
            return binding_id

    # to_backend nog niet getest en/f nodig gehad.
    def to_backend(self, binding_id):
        """ Give the external ID for an OpenERP ID

        :param binding_id: OpenERP ID for which we want the external id
        :return: backend identifier of the record
        """
        record = self.session.browse(self.model._name,
                                     binding_id)
        assert record
        res = {}
        return res

    def bind(self, external_id, binding_id):
        """ Create the link between an external ID and an OpenERP ID and
        update the last synchronization date.

        :param external_id: External ID to bind
        :param binding_id: OpenERP ID to bind
        :type binding_id: int
        """
        # avoid to trigger the export when we modify the `magento_id`
        context = self.session.context.copy()
        context['connector_no_export'] = True
        now_fmt = datetime.now().strftime(DEFAULT_SERVER_DATETIME_FORMAT)
        self.environment.model.write(
            self.session.cr,
            self.session.uid,
            binding_id,
            {'civicrm_id': external_id,
             'sync_date': now_fmt},
            context=context)
