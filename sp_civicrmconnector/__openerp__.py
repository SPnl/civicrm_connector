# -*- coding: utf-8 -*-
{'name': 'Odoo to CiviCRM for SP',
 'version': '0.1',
 'category': 'Connector',
 'depends': ['sp_base', 'connector', 'contract_distribution', ],
 'author': 'B-Informed',
 'description': """
Connector to connect Odoo with CiviCRM
""",
 'images': [],
 'demo': [],
 'data': [
     'security/ir.model.access.csv',
     'view/company.xml',
     'view/product.xml',
     'view/paymentterm.xml',
     'view/backend_model_view.xml',
     'view/partnerextend.xml'],
 'installable': True,
 'application': False,
 }
