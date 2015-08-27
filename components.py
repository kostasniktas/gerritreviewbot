#!/usr/bin/env python

import os
import re


class Component:
  def __init__ (self, name, owners = [], high_priority = False, all_owners_component = False):
    self.name = name
    self.owners = owners
    self.high_priority = high_priority
    self.all_owners_component = all_owners_component

  def __str__ (self):
    return str((self.name, self.owners, "HIGH" if self.high_priority else "NORMAL",
                "ALLOWNERS" if self.all_owners_component else "SINGLEOWNER"))

  def add_owner (self, owner):
    self.owners.append(owner)


def get_priority_components (components, high_priority=True):
  """Given a components dict, create a new dict based on the boolean"""
  high_priority_components = type(components)() # In case we have a special dict
  for i in components.keys():
    if components[i].high_priority == high_priority:
      high_priority_components[i] = components[i]
  return high_priority_components

def get_high_priority_components (components):
  """Given a components dict, create a new dict with only high priority items"""
  return get_priority_components (components, True)

def get_normal_priority_components (components):
  """Given a components dict, create a new dict with only normal priortiy items"""
  return get_priority_components (components, False)


def parse_component_text (text, starting_dict = dict()):
  """Create a component dict from a string.

  Uses the format:
  Component Name (owner1, owner2, owner3)
  com.package.something
  com.package.somethingelse.same

  Component Foo (owner6)
  com.anotherpackage.etc

  If owners are listed in [ ] instead of ( ), all the owners will be added

  Returns a dict() with mapping package -> Component
  """
  components = starting_dict

  if text is None or text.strip() == "":
    return components

  current_component = None
  for line in text.split(os.linesep):
    if line.lstrip().startswith("#"):
      pass # Comment line
    elif current_component is None:
      if line.strip() != "":
        parse_item_open = None
        if "(" in line:
          parse_item_open, parse_item_close = "(", ")"
        elif "[" in line:
          parse_item_open, parse_item_close = "[", "]"
        if parse_item_open is not None:
          index = line.index(parse_item_open)
          name = line[:index].strip()
          high_priority = False
          if name.startswith("HIGH"):
            high_priority = True
            name = name[len("HIGH "):]
          elif name.startswith("NORMAL"):
            name = name[len("NORMAL "):]
          owners = re.split("[\s,]+", line[index+1:line.index(parse_item_close)])
          current_component = Component(name, owners, high_priority, parse_item_open == "[")
    elif line.strip() == "":
      current_component = None
    else:
      components[line.strip()] = current_component
  return components


def find_component (components, item, delim="."):
  """Search for a component using normal strings.

  If an item is not found, the delim will be used to shorten
  the item until a match is found.

  It returns the first match it finds.  It is recommended to use
  the collections.OrderedDict() object if there is a priority.

  Returns a tuple: (str match_found, Component matching_component)
  """
  searchfor = str(item)
  lastsearch = None
  while True:
    #print "SearchFor: " + searchfor + "   LastSearch: " + str(lastsearch)
    if lastsearch is None:
      lastsearch = searchfor
    elif searchfor == lastsearch:
      return (None, None)

    if searchfor in components:
      return (searchfor, components[searchfor])
    else:
      lastsearch = searchfor
      searchfor = searchfor.rsplit(delim, 1)[0]
  return (None, None)


def find_component_re (components, item):
  """Search for a component using regex strings.

  Assumes the keys in the components dict are strings in the form
  of regexes.  Uses re.search()

  Returns a tuple: (str regex_match, Component matching_component)
  """
  for i in components.keys():
    m = re.search(i, item)
    if m is not None:
      return (i, components[i])
  return (None, None)




if __name__ == "__main__":
  from collections import OrderedDict
  components = {}
  with open ("regexComponents.txt") as f:
    components = parse_component_text ("".join(f.readlines()), starting_dict = OrderedDict())
  for i in components.keys():
    print i + ": " + str(components[i])
  print ""
  for i in get_high_priority_components(components).keys():
    print i + ": " + str(components[i])
  print ""
  for i in get_normal_priority_components(components).keys():
    print i + ": " + str(components[i])

