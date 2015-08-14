# -*- encoding: utf-8 -*-

from openerp.osv import fields
from openerp.osv.orm import TransientModel
from openerp.tools.safe_eval import safe_eval


class base_config_settings(TransientModel):
    _inherit = 'base.config.settings'

    # Getter / Setter Section
    def get_default_split_count(self, cr, uid, ids, context=None):
        icp = self.pool['ir.config_parameter']

        try:
            value = int(icp.get_param(cr, uid, 'sp_account_banking_sepa_direct_debit.split_count', 3000))
        except ValueError:
            value = 3000

        return {
            'split_count': value
        }

    def set_split_count(self, cr, uid, ids, context=None):
        config = self.browse(cr, uid, ids[0], context=context)
        icp = self.pool['ir.config_parameter']
        icp.set_param(cr, uid, 'sp_account_banking_sepa_direct_debit.split_count', config.split_count)

    # Columns Section
    _columns = {
        'split_count': fields.integer(
            'Split direct debit order in with this many lines',
        ),
    }
