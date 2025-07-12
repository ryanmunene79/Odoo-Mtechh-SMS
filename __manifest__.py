{
    "name": "MTech SMS Gateway Integration",
    "version": "18.0.1.0",  # Updated for Odoo 18
    "summary": "MTech SMS Gateway Integration",
    "description": """
        Complete integration with MTech SMS gateway including:
        - Direct SMS sending bypassing IAP
        - Delivery reports (DLR)
        - Marketing campaign support
        - Real-time queue processing
    """,
    "category": "Services/SMS",
    "author": "Wynda Africa",
    "maintainers": ["Brian Munene"],
    "website": "https://wynda.africa",
    "depends": ["base", "sms", "mass_mailing_sms", "web"],
    "data": [
        "security/ir.model.access.csv",
        "views/mtech_provider_views.xml",
        "data/ir_cron.xml",
    ],
    "demo": ["demo/mtech_provider_demo.xml"],  # Optional demo data
    "installable": True,
    "application": True,
    "auto_install": False,
    "license": "LGPL-3",
}
