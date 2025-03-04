# Implementation of "Thinking Like Transformers" (https://arxiv.org/pdf/2106.06981.pdf)
# full repo: https://github.com/tech-srl/RASP
# @yashbonde - 18.06.2021
# MIT License
#
# Why build this?
# - learning how to write languages is the best way to learn how to minimise useless shit
#   and maximise simplicity of code + was fun to code whilst in Deep Thoughts!
#
# Where can I use this?
# - See the examples, if it's not there then will add it later.
#
# Things that are different from the paper
# -
# TODO:
# - implement conditionals
# - additional operators such as `in`, `sort`, `count`

import string
import numpy as np
import torch
import einops as ein

# NOTE: This is a demo code and not meant to be a production thing
# changing the vocab will break some tests, so for the sake of your
# and my sanity don't change this.
vocab = {k:i for i,k in enumerate(string.ascii_lowercase + "$")}
ivocab = {i:k for k,i in vocab.items()}

# ---- built in
def tokens(x, bos = False):
  """
  if bos == True, then output has bos tag added

  ### Always PAD ###

  # tokens("hello") = [ 7,  4, 11, 11, 14]
  # tokens(tokens("hello")) = "hello"
  # tokens(["hello", "hello"]) = [[7,  4, 11, 11, 14], [7, 4, 11, 11, 14]]
  # tokens([[7,  4, 11, 11, 14], [7, 4, 11, 11, 14]]) = ["hello", "hello"]

  Logic Flow:
    # Case A (str only): "hello"
    # Case B (list of str): ["hello", "hello"]
    # Case C (tensor 1D): [ 7,  4, 11, 11, 14]
    # Case D (tensor 2D): [[ 7,  4, 11, 11, 14], [ 7,  4, 11, 11, 14]]

  can consume strings, lists, arrays and tensors
  """

  if isinstance(x, str):
    # Case A (str only): "hello"
    out = torch.Tensor([vocab["$"]] + [vocab[t] for t in x.lower()]).long()
    if not bos:
      out = out[1:]
    return out
  elif isinstance(x, list) and isinstance(x[0], str):
    # Case B (list of str): ["hello", "hello"]
    m = max([len(y) for y in x])
    for i,y in enumerate(x):
      x[i] = x[i] + "".join(["$" for _ in range(m - len(x[i]))])
    return torch.cat([tokens(s, bos).unsqueeze(0) for s in x]).long()
  else:
    assert isinstance(x, (torch.Tensor, np.ndarray)), "Can consume only strings and torch.Tensors / np.ndarrays"
    # input is likely a tensor
    if len(x.shape) == 1:
      # Case C (tensor 1D): [ 7,  4, 11, 11, 14]
      out = "".join([ivocab[t] for t in x.tolist()])
      # FORCE REMOVE PADDING
      if "$" in out[1:]:
        out = out[:out[1:].index("$")]
      if not bos and out[0] == "$":
        out = out[1:]
      out = out
      return out
    else:
      # Case D (tensor 2D): [ [ 7,  4, 11, 11, 14], [ 7,  4, 11, 11, 14]]
      return [tokens(s, bos) for s in x]

def indices(x):
  # indices("hello") = [0,1,2,3,4]
  return torch.arange(len(x)).float()

def length(x):
  # length("hello") = [5,5,5,5,5]
  return torch.ones(len(x)) * len(x)


# --- element wise
def logical(x, op, y = None):
  # logical(x, "and", y)
  def _or(x, y):
    return torch.logical_or(x.contiguous().view(-1), y.contiguous().view(-1)).view(x.shape)
  def _and(x, y):
    return torch.logical_and(x.contiguous().view(-1), y.contiguous().view(-1)).view(x.shape)
  def _not(x, y):
    return torch.logical_not(x.contiguous().view(-1)).view(x.shape)
  def _xor(x, y):
    return torch.logical_xor(x.contiguous().view(-1), y.contiguous().view(-1)).view(x.shape)
  
  assert op in ["or", "and", "not", "xor"], f"`{op}` not supported"
  if op != "not":
    assert x.shape == y.shape, f"Shapes must be same, got {x.shape}, {y.shape}"
  out = {"or": _or, "and": _and, "not": _not, "xor": _xor}[op](x, y)
  return out

def elementwise(x, op, y):
  # elementwise(x, "-", y)
  if op in ["or", "and", "not", "xor"]:
    return logical(x, op, y)

  def _add(x, y): return x + y
  def _mul(x, y): return x * y
  def _sub(x, y): return x - y
  def _div(x, y):
    out = torch.div(x, y)
    out[out == float("inf")] = 0
    out = torch.nan_to_num(out, 0)
    return out

  assert x.shape == y.shape, f"Shapes must be same, got {x.shape}, {y.shape}"
  assert op in ["+", "-", "*", "/"], f"`{op}` not supported"

  out = {"+":_add, "-":_sub, "*":_mul, "/":_div}[op](x, y)
  return out


# --- select
def select(m1: torch.Tensor, m2, op):
  # creating boolean matrices called "selectors"
  if isinstance(m2, (bool, int)):
    m2 = torch.ones(m1.shape) * m2
  
  assert len(m1.shape) == 1
  assert len(m2.shape) == 1
  
  rows = ein.repeat(m1, "w -> n w", n = m2.shape[0])
  cols = ein.repeat(m2, "h -> h n", n = m1.shape[0])

  init_shape = rows.shape
  out = {
    "==": torch.eq,
    "!=": lambda *x: ~torch.eq(*x),
    "<=": torch.less_equal,
    "<": torch.less,
    ">": torch.greater,
    ">=": torch.greater_equal,
  }[op](rows.contiguous().view(-1), cols.contiguous().view(-1))
  out = out.view(*init_shape)

  return out
  
# --- aggregate
def aggregate(s, x, agg = "mean"):
  # collapsing selectors and s-ops into new s-ops
  x = ein.repeat(x, "w -> n w", n = s.shape[0])
  sf = s.float()
  y = x * sf
  
  if agg == "mean":
    ym = y.sum(1) / sf.sum(1)
  else:
    raise ValueError(f"agg: `{agg}` not found")
  
  return torch.nan_to_num(ym, 0)

# --- simple select aggregate
def flip(x):
  i = indices(x); l = length(x)
  return select(i, l-i-1, "==")

# --- selector_width

# def selector_width(x):
#   pass

# def selector_width (sel ,assume_bos = False):
#   light0 = indicator ( indices == 0)
#   or0 = sel or select_eq ( indices ,0)
#   and0 =sel and select_eq ( indices ,0)
#   or0_0_frac =aggregate (or0 , light0 )
#   or0_width = 1 / or0_0_frac
#   and0_width = aggregate (and0 ,light0 ,0)
# 
#   # if has bos , remove bos from width
#   # (doesn ’t count , even if chosen by
#   # sel) and return .
#   bos_res = or0_width - 1
# 
#   # else , remove 0 - position from or0 ,
#   # and re -add according to and0 :
#   nobos_res = bos_res + and0_width
# 
#   return bos_res if assume_bos else
#   nobos_res