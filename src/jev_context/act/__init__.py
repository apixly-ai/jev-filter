"""Hosted execution: observe, let Jev choose among program-enumerated actions, execute, verify.

Jev never produces selectors, coordinates, commands or scripts. Every executable target is
resolved from an observation the program made, re-checked immediately before input, and every
step is archived. Irreversible actions stop for confirmation unless the caller opts in.
"""
