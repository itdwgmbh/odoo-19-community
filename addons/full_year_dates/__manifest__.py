{
    "name": "Full Year Dates",
    "version": "19.0.1.0.1",
    "category": "Tools",
    "summary": "Show the year in backend dates and chatter timestamps",
    "author": "IT-DW GmbH",
    "website": "https://www.it-dw.com",
    "license": "LGPL-3",
    "depends": ["mail", "web"],
    "assets": {
        "web.assets_backend": [
            "full_year_dates/static/src/date_with_year.js",
        ],
    },
    "installable": True,
    "application": False,
    "auto_install": False,
}
