import json
import datetime
import dateutil.parser

import botUtils.enums

CONVERTERS = {
    'datetime': dateutil.parser.parse
    #'dscState': dateutil.parser.parse
}

class Encoder(json.JSONEncoder):
        def default(self, obj):
            if isinstance(obj, datetime.datetime):
                return {"val": obj.isoformat(), "_spec_type": "datetime"}
            #if isinstance(obj, enums.DscState):
            #    return {"val": str(obj), "_spec_type": "dscState"}
            else:
                return super().default(self, obj)

def decoder_obj_hook(obj):
    _spec_type = obj.get('_spec_type')
    if not _spec_type:
        return obj

    if _spec_type in CONVERTERS:
        return CONVERTERS[_spec_type](obj['val'])
    else:
        raise Exception('Unknown {}'.format(_spec_type))

