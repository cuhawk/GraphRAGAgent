import inspect

import pyoxigraph as ox

print("query:", inspect.signature(ox.Store.query))
print(inspect.getdoc(ox.Store.query)[:900])
