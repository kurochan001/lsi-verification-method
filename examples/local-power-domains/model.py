"""Expected values from the power intent table, the requests and a ledger of the register values.

The model knows what the two domains compute and reads everything about power from the table:
which registers are retained, their reset values, the isolation values, and which states and
transitions are legal. It has no phases and no cycle counts of the controller.
"""
from collections import deque


class PowerModel:
    def __init__(self, intent):
        self.intent = intent
        self.domains = intent['domains']
        self.reset()

    def reset(self):
        self.on = {key: 0 for key in self.domains}
        self.values = {r['name']: r['reset'] for d in self.domains.values() for r in d['registers']}
        self.held = {o['name']: 0 for d in self.domains.values() for o in d['outputs']}
        self.path = []

    def state_name(self, on=None):
        on = self.on if on is None else on
        return next(name for name, state in self.intent['states'].items() if state == on)

    def target(self, request):
        """A domain is wanted when it is requested together with every domain it requires."""
        want = {}
        for key, domain in self.domains.items():
            want[key] = int(bool(request[key]) and all(want[other] for other in domain['requires']))
        return want

    def raw_outputs(self):
        v = self.values
        return dict(a_sum=v['acc'], a_idle_n=1 - v['fired'], a_last=v['scratch'], b_count=v['count'], b_mode=v['mode'])

    def switch(self, key, value):
        domain = self.domains[key]
        if value:  # power-up: retained registers keep the saved value, the others take their reset value
            for register in domain['registers']:
                if not register['retained']:
                    self.values[register['name']] = register['reset']
        else:      # power-down: the outputs with `hold` remember what they showed
            raw = self.raw_outputs()
            for output in domain['outputs']:
                self.held[output['name']] = raw[output['name']]
        self.on[key] = value

    def power(self, request):
        """Move to the wanted state along legal transitions; returns the names of the transitions."""
        goal = self.state_name(self.target(request))
        start = self.state_name()
        queue, seen = deque([(start, [])]), {start}
        while queue:
            name, path = queue.popleft()
            if name == goal:
                break
            for transition, (source, target) in self.intent['transitions'].items():
                if source == name and target not in seen:
                    seen.add(target)
                    queue.append((target, path + [transition]))
        else:
            raise ValueError(f'no legal path from {start} to {goal}')
        for transition in path:
            source, target = (self.intent['states'][n] for n in self.intent['transitions'][transition])
            key = next(k for k in self.domains if source[k] != target[k])
            self.switch(key, target[key])
        self.path = path
        return path

    def operate(self, select, data):
        """One operand for domain A (select 0) or B (select 1); returns whether it is accepted."""
        v = self.values
        if not self.on['b' if select else 'a']:
            return False
        if not select:
            v['acc'] = (v['acc'] + data) & 0xff
            v['scratch'] = data
        elif data & 0x80:
            v['mode'] = data & 0xf
        else:
            v['count'] = (v['count'] + (data & 0x7f) + (v['acc'] & 1)) & 0xff
        return True

    def outputs(self):
        """What the always-on side sees: the raw value of a domain that is on, else the isolation value."""
        raw, seen = self.raw_outputs(), {}
        for key, domain in self.domains.items():
            for output in domain['outputs']:
                name = output['name']
                clamp = {'zero': 0, 'one': (1 << output['width']) - 1, 'hold': self.held[name]}[output['isolation']]
                seen[name] = raw[name] if self.on[key] else clamp
        return seen
