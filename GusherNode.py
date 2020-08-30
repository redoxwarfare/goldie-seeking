from GusherMap import BASKET_LABEL
from copy import deepcopy
from statistics import mean, pstdev
from pyparsing import Regex, Forward, Suppress, Optional, Group

# Flag to indicate gusher is non-findable
NEVER_FIND_FLAG = '*'


class GusherNode:
    def __init__(self, name, gusher_map=None, findable=True):
        self.name = name
        self.low = None  # next gusher to open if this gusher is low
        self.high = None  # next gusher to open if this gusher is high
        self.parent = None  # gusher previously opened in sequence
        self.findable = findable  # whether it is possible to find the Goldie at this gusher
        # if findable is False, the gusher is being opened solely for information (e.g. gusher G on Ark Polaris)
        # non-findable nodes still count towards their children's costs, but don't count towards tree's objective score
        self.size = 1 if findable else 0  # number of findable nodes in subtree rooted at this node
        self.distance = 1  # distance from parent gusher
        self.latency = 0  # if Goldie is in this gusher, how long it takes to find Goldie by following decision tree
        # latency = total distance traveled on the path from root node to this node
        self.total_latency = 0  # sum of latencies of this node's findable descendants
        if gusher_map:
            self.weight = gusher_map.weight(name)  # risk weight for this gusher
        else:
            self.weight = 1
        self.risk = 0  # if Goldie is in this gusher, roughly how much trash is spawned by following decision tree
        # Trash spawned by a given gusher is multiplied by the gusher's weight
        # This does not mean the gusher actually spawns more fish; it is just a way of telling the algorithm that
        #   some gushers spawn more dangerous trash than others (e.g. gushers next to basket)
        self.total_risk = 0  # sum of risks of this node's findable descendants

    def __str__(self):
        return self.name + (NEVER_FIND_FLAG if not self.findable else "")

    def __repr__(self):
        return write_tree(self) + f'; time: {self.total_latency}, risk: {self.total_risk}}}'

    def __iter__(self):
        yield self
        if self.high:
            yield from self.high.__iter__()
        if self.low:
            yield from self.low.__iter__()

    def __eq__(self, other):
        if not other:
            return False
        else:
            return self.name == other.name and self.weight == other.weight and self.findable == other.findable

    # Override deepcopy so that it does not copy non-root nodes' cost attributes (weight, size, latency, etc.)
    # This improves performance without sacrificing any accuracy
    # noinspection PyDefaultArgument
    def __deepcopy__(self, memodict={}):
        tree_copy = GusherNode(self.name, findable=self.findable)
        if not self.parent:
            cost_attrs = ('size', 'distance', 'latency', 'total_latency', 'weight', 'risk', 'total_risk')
            tree_copy.__dict__.update({attr: self.__dict__.get(attr) for attr in cost_attrs})
        if self.high:
            tree_copy.high = deepcopy(self.high)
            tree_copy.high.parent = tree_copy
        if self.low:
            tree_copy.low = deepcopy(self.low)
            tree_copy.low.parent = tree_copy
        return tree_copy

    def is_same_tree(self, other):
        if not other:
            return False
        if not (self == other):
            return False
        if self.high:
            same_high = self.high.is_same_tree(other.high)
        else:
            same_high = not other.high
        if self.low:
            same_low = self.low.is_same_tree(other.low)
        else:
            same_low = not other.low
        return same_high and same_low

    def add_children(self, high, low, dist_h=1, dist_l=1):
        size_h, size_l = 0, 0
        totlat_h, totlat_l = 0, 0
        totrisk_h, totrisk_l = 0, 0
        if high:
            assert not self.high, f'gusher {self} already has high child {self.high}'
            assert not high.parent, f'gusher {high} already has parent {high.parent}'
            self.high = high
            self.high.parent = self
            self.high.distance = dist_h
            size_h = self.high.size
            totlat_h = self.high.total_latency
            totrisk_h = self.high.total_risk
        if low:
            assert not self.low, f'gusher {self} already has low child {self.low}'
            assert not low.parent, f'gusher {low} already has parent {low.parent}'
            self.low = low
            self.low.parent = self
            self.low.distance = dist_l
            size_l = self.low.size
            totlat_l = self.low.total_latency
            totrisk_l = self.low.total_risk
        self.size = size_l + size_h + (1 if self.findable else 0)
        self.total_latency = totlat_l + dist_l*size_l + totlat_h + dist_h*size_h
        self.total_risk = totrisk_l + totrisk_h + self.weight*self.total_latency

    def findable_nodes(self):
        return (node for node in self if node.findable)

    def update_costs(self, gusher_map=None, start=BASKET_LABEL):
        """Update distances, latencies and risks of this node's descendants. Should be called on root of tree."""
        def recurse(node, parent_latency, total_predecessor_weight):
            if node.parent:
                if gusher_map:
                    node.distance = gusher_map.distance(node.parent.name, node.name)
                node.latency = parent_latency + node.distance
                node.risk = node.parent.risk + total_predecessor_weight*node.distance
            else:
                # Latency of root node is distance between start (i.e. basket) and root node
                if gusher_map:
                    node.latency = gusher_map.distance(start, node.name)
                    node.total_latency += node.latency*node.size
                else:
                    node.latency = 0
                node.risk = 0

            if node.high:
                recurse(node.high, node.latency, total_predecessor_weight + node.weight)
            if node.low:
                recurse(node.low, node.latency, total_predecessor_weight + node.weight)

        recurse(self, 0, 0)

    def calc_tree_score(self, gusher_map=None, start=BASKET_LABEL):
        """Calculate and store the total latency and total risk of the tree rooted at this node."""
        self.update_costs(gusher_map, start)
        self.total_latency, self.total_risk = 0, 0
        for node in self.findable_nodes():
            self.total_latency += node.latency
            self.total_risk += node.risk

    def validate(self):
        """Check that tree is a valid strategy tree."""
        def recurse(node, predecessors):
            # can't open the same gusher twice
            assert str(node) not in predecessors, f'node {node} found in own predecessors: {predecessors}'

            if node.high or node.low:
                pred_new = predecessors.copy()
                pred_new.add(str(node))

                # make sure parent/child references are consistent
                if node.high:
                    assert node.high.parent == node, f'node {node}, node.high {node.high}, ' \
                                                     f'node.high.parent {node.high.parent}'
                    recurse(node.high, pred_new)
                if node.low:
                    assert node.low.parent == node, f'node {node}, node.low {node.high}, ' \
                                                    f'node.low.parent {node.low.parent}'
                    recurse(node.low, pred_new)
            else:
                # reaching a leaf node must guarantee that the Goldie will be found
                assert node.findable, f'node {node} is non-findable leaf node'
        recurse(self, set())

    def report(self, gusher_map=None):
        self.update_costs(gusher_map)
        latencies = {str(node): node.latency for node in self.findable_nodes()}
        risks = {str(node): node.risk for node in self.findable_nodes()}
        compact_str = write_tree(self)
        output = '-'*len(compact_str) + '\n' + \
                 compact_str + '\n' + \
                 write_instructions(self) + '\n' + \
                 f"times: {{{', '.join(f'{node}: {time:0.2f}' for node, time in sorted(latencies.items()))}}}\n"\
                 f"'risks: {{{', '.join(f'{node}: {risk:0.2f}' for node, risk in sorted(risks.items()))}}}\n"\
                 f"avg. time: {mean(latencies.values()):0.2f} +/- {pstdev(latencies.values()):0.2f}\n"\
                 f"avg. risk: {mean(risks.values()):0.2f} +/- {pstdev(risks.values()):0.2f}"
        return output


def write_tree(root):
    """Write the strategy encoded by the subtree rooted at 'root' in modified Newick format.
    V(H, L) represents the tree with root node V, high subtree H, and low subtree L.
    A node name followed by * indicates that the gusher is being opened solely for information and the Goldie will
    never be found there."""
    if root.high and root.low:
        return f'{root}({write_tree(root.high)}, {write_tree(root.low)})'
    elif root.high:
        return f'{root}({write_tree(root.high)},)'
    elif root.low:
        return f'{root}(,{write_tree(root.low)})'
    else:
        return f'{root}'


# Decision tree grammar
node = Regex(rf'\w+[{NEVER_FIND_FLAG}]?')
LPAREN, COMMA, RPAREN = map(Suppress, '(,)')
tree = Forward()
subtree = Group(Optional(tree))
subtrees = LPAREN + subtree.setResultsName('high') + COMMA + subtree.setResultsName('low') + RPAREN
tree << node.setResultsName('root') + Optional(subtrees)


def read_tree(tree_str, gusher_map, start=BASKET_LABEL):
    """Read the strategy encoded in tree_str and build the corresponding decision tree.
    V(H, L) represents the tree with root node V, high subtree H, and low subtree L.
    A node name followed by * indicates that the gusher is being opened solely for information and the Goldie will
    never be found there."""

    def build_tree(tokens):  # recursively convert ParseResults object into GusherNode tree
        findable = tokens.root[-1] is not NEVER_FIND_FLAG
        rootname = tokens.root.rstrip(NEVER_FIND_FLAG)
        root = GusherNode(rootname, gusher_map=gusher_map, findable=findable)
        if tokens.high or tokens.low:
            high, low = None, None
            dist_h, dist_l = 1, 1
            if tokens.high:
                high = build_tree(tokens.high)
                if gusher_map:
                    dist_h = gusher_map.distance(rootname, high.name)
            if tokens.low:
                low = build_tree(tokens.low)
                if gusher_map:
                    dist_l = gusher_map.distance(rootname, low.name)
            root.add_children(high=high, low=low, dist_h=dist_h, dist_l=dist_l)
        return root

    tokens = tree.parseString(tree_str)
    root = build_tree(tokens)

    root.calc_tree_score(gusher_map, start)
    return root


def write_instructions(tree):
    """Convert strategy tree into human-readable instructions."""
    def recurse(subtree, depth):
        indent = "   "*depth
        result = ""
        if subtree.size > 2 or (subtree.high and subtree.low):
            result += f"open {subtree}\n"
            if subtree.high:
                result += indent + f"{subtree} high --> " + recurse(subtree.high, depth+1)
            if subtree.low:
                result += indent + f"{subtree} low --> " + recurse(subtree.low, depth+1)
        else:
            result = ', '.join(str(node) for node in subtree) + '\n'
        return result
    return recurse(tree, 0).strip('\n ')
