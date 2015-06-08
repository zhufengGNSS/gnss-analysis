#!/usr/bin/env python
# Copyright (C) 2015 Swift Navigation Inc.
# Contact: Bhaskar Mookerji <mookerji@swiftnav.com>
#
# This source is subject to the license found in the file 'LICENSE' which must
# be be distributed together with this source. All other rights reserved.
#
# THIS CODE AND INFORMATION IS PROVIDED "AS IS" WITHOUT WARRANTY OF ANY KIND,
# EITHER EXPRESSED OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE IMPLIED
# WARRANTIES OF MERCHANTABILITY AND/OR FITNESS FOR A PARTICULAR PURPOSE.

"""Interpolation and indexing utilities for Pandas tables. Most of
these are for indexing quantities (e.g., Piksi MsgPrint) that don't
have explicit GPS times.

"""

from gnss_analysis.stats_utils import truthify
import numpy as np
import pandas as pd
import warnings

USEC_TO_SEC = 1e-6
MSEC_TO_SEC = 1e-3

import warnings
warnings.filterwarnings('ignore', category=pd.io.pytables.PerformanceWarning)


def interpolate_gpst_model(df_gps):
  """Produces a linear mapping between the host's log offset (seconds)
  and GPS offset (seconds) from the beginning of the log. Assumes that
  the first GPS time as the initial GPS time.

  Parameters
  ----------
  host_offset : pandas.DataFrame

  Returns
  ----------
  pandas.stats.ols.OLS

  """
  init_gps_t = pd.to_datetime(df_gps['index'][0])
  gps_offset = pd.to_datetime(df_gps['index']) - init_gps_t
  gps_offset_y = gps_offset / np.timedelta64(1, 's')
  log_offset_x = df_gps.host_offset*MSEC_TO_SEC
  return pd.ols(y=gps_offset_y, x=log_offset_x, intercept=True)


def apply_gps_time(host_offset, init_date, model):
  """Interpolates a GPS datetime based on a record's host log offset.

  Parameters
  ----------
  host_offset : int
    Second offset since beginning of log.
  model : pandas.stats.ols.OLS
    Pandas OLS model mapping host offset to GPS offset

  Returns
  ----------
  pandas.tslib.Timestamp

  """
  gps_offset = model.beta.x * host_offset + model.beta.intercept
  return init_date + pd.Timedelta(seconds=gps_offset)


def get_gps_time_col(store, tabs, gpst_col='approx_gps_time', verbose=False):
  """Given an HDFStore and a list of tables in that HDFStore,
  interpolates GPS times for the desired tables and inserts the
  appropriate columns in the table.

  Parameters
  ----------
  store : pandas.HDFStore
    Pandas HDFStore
  gpst_col : str
    Key to insert new column
  tabs : list
    List of tables to interpolate for
  verbose : bool
    Verbose outoput

  """
  idx = store.rover_spp.T.host_offset.reset_index()
  model = interpolate_gpst_model(idx)
  init_date = store.rover_spp.T.index[0]
  f = lambda t1: apply_gps_time(t1*MSEC_TO_SEC, init_date, model)
  for tab in tabs:
    # Because this is largely a research tool and the tables are
    # constantly in flux, just warn if the specified table isn't in
    # the table when interpolating.
    if verbose:
      print "Interpolating approx_gps_time for %s." % tab
    if tab not in store:
      warnings.warn("%s not found in Pandas table" % tab, UserWarning)
    elif isinstance(store[tab], pd.DataFrame):
      dft = store[tab].T
      dft[gpst_col] = store[tab].T.host_offset.apply(f)
      store[tab] = dft.T
    elif isinstance(store[tab], pd.Panel):
      y = {}
      for prn in store[tab].items:
        y[prn] = store[tab][prn, 'host_offset', :].dropna().apply(f)
      ans = store[tab].transpose(1, 0, 2)
      ans['approx_gps_time'] = pd.DataFrame(y).T
      store[tab] = ans.transpose(1, 0, 2)


def reindex_tables(store, tabs, gpst_col='approx_gps_time', verbose=False):
  """"Reindexes the tables in an HDFStore using the specified column.

  Parameters
  ----------
  store : pandas.HDFStore
    Pandas HDFStore
  tabs : list
    List of tables to interpolate for
  gpst_col : str
    Key to insert new column

  """
  for tab in tabs:
    if verbose:
      print "Reindexing with approx_gps_time for %s." % tab
    if tab not in store:
      warnings.warn("%s not found in Pandas table" % tab, UserWarning)
    elif isinstance(store[tab], pd.DataFrame):
      store[tab] = store[tab].T.set_index(gpst_col).T
    elif isinstance(store[tab], pd.Panel):
      assert NotImplementedError


def find_largest_gaps(idx, n=10):
  """Given a time series index, finds the n largest gaps.  you may use
  this, for example, to find the time (endpoint) and duration of gaps
  in satellite observations.

  Parameters
  ----------
  idx : Pandas DatetimeIndex
  n : int
    n largest to return. Defaults to 10.

  Returns
  -------
  Pandas DatetimeIndex

  """
  adj =(idx - idx[0])/pd.Timedelta('00:00:01')
  return pd.Series(adj, idx).diff().nlargest(n)


def get_sdiff(obs_type, rover_obs,  base_obs):
  """For a given observation type, produces single-differenced
  observations from the base station and the rover.

  Parameters
  ----------
  obs_type : observation key, either 'P' (pseudorange) or 'L' (carrier phase)
  rover_obs : Panel of Rover observations
  base_obs : Panel of Base observations

  Returns
  -------
  DataFrame of single-difference observations

  """
  assert obs_type in ['P', 'L'], "Invalid obs_type: %s" % obs_type
  sdiff = rover_obs[:, obs_type, :] - base_obs[:, obs_type, :]
  return sdiff.dropna(how='all', axis=[0, 1]).T


def get_ref_sat(sdiff):
  """Given a set of single-difference observations, determine a
  reference satellite. By convention, this is the satellite with the
  most observations.

  Parameters
  ----------
  sdiff : DataFrame of single-difference observations.

  Returns
  -------
  int, prn of reference sat

  """
  return sdiff.count().argmax()


def get_ddiff(ref_sat, sdiff):
  """Given a reference satellite and sdiff observations, returns double
  difference observations.

  Parameters
  ----------
  ref_sat : int, reference satellite
  sdiff : DataFrame of single-difference observations.

  Returns
  -------
  Pandas DatetimeIndex

  """
  return sdiff - sdiff[ref_sat]


def get_ddiff_t(ddiff):
  """Produces "truthified" double-difference observation. Essentially a median
  filter/smoothing of the double-difference observations.

  Parameters
  ----------
  ddiff : DataFrame of double-differenced observations

  Returns
  -------
  Pandas DataFrame
  """
  return ddiff - truthify(ddiff)
