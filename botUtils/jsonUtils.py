import json
import datetime
import dateutil.parser

import botUtils.enums

CONVERTERS = {
    'datetime': dateutil.parser.parse
}


class Encoder(json.JSONEncoder):
    """JSON encoder class for data types w/o built-in encoder"""

    def default(self, obj):
        if isinstance(obj, datetime.datetime):
            return {"val": obj.isoformat(), "_spec_type": "datetime"}
        else:
            return super().default(self, obj)


def decoder_obj_hook(obj):
    """JSON decoder object_hook for data types w/o built-in decoder"""

    _spec_type = obj.get('_spec_type')
    if not _spec_type:
        return obj

    if _spec_type in CONVERTERS:
        return CONVERTERS[_spec_type](obj['val'])
    else:
        raise Exception('Unknown {}'.format(_spec_type))

