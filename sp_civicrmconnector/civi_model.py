from openerp.osv import fields, orm

from openerp.addons.connector.session import ConnectorSession


class civicrm_backend(orm.Model):
    _name = 'civicrm.backend'
    _description = 'civicrm Backend'
    _inherit = 'connector.backend'

    _backend_type = 'civicrm'

    def _select_versions(self, cr, uid, context=None):
        """ Available versions

        Can be inherited to add custom versions.
        """
        return [('7.0', '7.0')]

    _columns = {
        'version': fields.selection(
            _select_versions,
            string='Version',
            required=True),
        'url': fields.char('URL', required=True),
        'username': fields.char('Username', required=False),
        'password': fields.char('Password', required=False),
        'site_key': fields.char('Site api key', required=True),
        'api_key': fields.char('User api key', required=True),
    }
    _defaults = {
        'version': '7.0',
    }
