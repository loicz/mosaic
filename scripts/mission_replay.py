"""Index recorded states without loading repeated full trails into memory."""
import json
import threading


class Replay:
    def __init__(self, path):
        self.path = path
        self.offset = 0
        self.entries = []
        self.lock = threading.Lock()

    def index(self):
        with self.lock, self.path.open('rb') as stream:
            stream.seek(self.offset)
            while True:
                offset = stream.tell()
                line = stream.readline()
                # A writer can be in the middle of flushing a state. Retry it
                # next time, never permanently skip a partially written frame.
                if not line.endswith(b'\n'): break
                self.offset = stream.tell()
                try: record = json.loads(line)
                except (ValueError, UnicodeDecodeError): continue
                if record.get('kind') == 'state':
                    state = record['value']
                    self.entries.append((offset, state['time'], state['phase']))
            return dict(schema='mosaic.replay.index.v1',
                        frames=[dict(time=t, phase=p) for _,t,p in self.entries])

    def frame(self, index):
        with self.lock:
            if index < 0 or index >= len(self.entries): raise IndexError(index)
            offset = self.entries[index][0]
        with self.path.open('rb') as stream:
            stream.seek(offset)
            state = json.loads(stream.readline())['value']
        return {k:v for k,v in state.items() if k != 'token'}
