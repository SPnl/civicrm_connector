# -*- coding: utf-8 -*-

from openerp.osv import fields, orm

import pprint


class product(orm.Model):
    _inherit = 'product.product'
    _columns = {
        'financial_type_id': fields.integer('financial_type on Civicrm'),
        'financial_account_id': fields.integer('financial_account_id on Civicrm'),
    }

