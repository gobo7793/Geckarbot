import json
import datetime

# pylint: disable=arguments-differ

CONVERTERS = {
    'datetime': datetime.datetime.fromisoformat
}


class Encoder(json.JSONEncoder):
    """JSON encoder class for data types w/o built-in encoder"""

    def default(self, o):
        if isinstance(o, datetime.datetime):
            return {"val": o.isoformat(), "_spec_type": "datetime"}
        return super().default(o)


class Decoder(json.JSONDecoder):
    """JSON decoder to include data types w/o built-in decoder"""
    def decode(self, s):
        result = super().decode(s)
        return self._decode(result)

    def _decode(self, o):
        if isinstance(o, str):
            try:
                return int(o)
            except ValueError:
                return o
        elif isinstance(o, dict):
            _spec_type = o.get('_spec_type')
            if not _spec_type:
                return {self._decode(k): self._decode(v) for k, v in o.items()}

            if _spec_type in CONVERTERS:
                return CONVERTERS[_spec_type](o['val'])
            raise Exception('Unknown {}'.format(_spec_type))
        elif isinstance(o, list):
            return [self._decode(v) for v in o]
        return o
