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
{
    'name': 'SEPA Direct Debit Batch confirmer',
    'summary': 'Confirms direct debit payment orders in batch',
    'version': '0.1',
    'license': 'AGPL-3',
    'author': 'B-informed',
    'website': 'http://www.B-informed.nl',
    'category': 'Banking addons',
    'depends': ['sp_account_banking_sepa_direct_debit', 'connector', ],
    'data': [
        'wizard/confirm_wizard_view.xml',
    ],
    'demo': ['sepa_direct_debit_demo.xml'],
    'description': '''
Confirms direct debit payment orders in batch mode with the openerp-connector

Based on oca's account_move_batch_validate by camptocamp.
Uses the Odoo connector, see http://odoo-connector.com/
''',
    'active': False,
    'installable': True,
}
