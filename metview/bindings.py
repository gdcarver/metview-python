#
# Copyright 2017-2018 B-Open Solutions srl.
# Copyright 2017-2018 European Centre for Medium-Range Weather Forecasts (ECMWF).
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import datetime
import keyword
import os
import pkgutil
import signal
import tempfile
import builtins

import cffi
import numpy as np


def string_from_ffi(s):
    return ffi.string(s).decode('utf-8')


class MetviewInvoker:
    """Starts a new Metview session on construction and terminates it on program exit"""

    def __init__(self):
        """
        Constructor - starts a Metview session and reads its environment information
        Raises an exception if Metview does not respond within 5 seconds
        """

        self.debug = (os.environ.get("METVIEW_PYTHON_DEBUG", '0') == '1')

        # check whether we're in a running Metview session
        if 'METVIEW_TITLE_PROD' in os.environ:
            self.persistent_session = True
            self.info_section = {'METVIEW_LIB': os.environ['METVIEW_LIB']}
            return

        import atexit
        import time
        import subprocess

        if self.debug:
            print('MetviewInvoker: Invoking Metview')
        self.persistent_session = False
        self.metview_replied = False
        self.metview_startup_timeout = 5  # seconds

        # start Metview with command-line parameters that will let it communicate back to us
        env_file = tempfile.NamedTemporaryFile(mode='rt')
        pid = os.getpid()
        # print('PYTHON:', pid, ' ', env_file.name, ' ', repr(signal.SIGUSR1))
        signal.signal(signal.SIGUSR1, self.signal_from_metview)
        # p = subprocess.Popen(['metview', '-edbg', 'tv8 -a', '-slog', '-python-serve', env_file.name, str(pid)], stdout=subprocess.PIPE)
        metview_flags = ['metview', '-nocreatehome', '-python-serve', env_file.name, str(pid)]
        if self.debug:
            metview_flags.insert(2, '-slog')
            print('Starting Metview using these command args:')
            print(metview_flags)

        try:
            subprocess.Popen(metview_flags)
        except Exception as exp:
            print("Could not run the Metview executable ('metview'); check that the binaries for Metview (version 5 at least) are installed and are in the PATH.")
            raise exp


        # wait for Metview to respond...
        wait_start = time.time()
        while not(self.metview_replied) and (time.time() - wait_start < self.metview_startup_timeout):
            time.sleep(0.001)

        if not(self.metview_replied):
            raise Exception('Command "metview" did not respond within ' + str(self.metview_startup_timeout) + ' seconds. ' +
                            'At least Metview 5 is required, so please ensure it is in your PATH, as earlier ' +
                            'versions will not work with the Python interface.')

        self.read_metview_settings(env_file.name)

        # when the Python session terminates, we should destroy this object so that the Metview
        # session is properly cleaned up. We can also do this in a __del__ function, but there can
        # be problems with the order of cleanup - e.g. the 'os' module might be deleted before
        # this destructor is called.
        atexit.register(self.destroy)

    def destroy(self):
        """Kills the Metview session. Raises an exception if it could not do it."""

        if self.persistent_session:
            return

        if self.metview_replied:
            if self.debug:
                print('MetviewInvoker: Closing Metview')
            metview_pid = self.info('EVENT_PID')
            try:
                os.kill(int(metview_pid), signal.SIGUSR1)
            except Exception as exp:
                print("Could not terminate the Metview process pid=" + metview_pid)
                raise exp

    def signal_from_metview(self, *args):
        """Called when Metview sends a signal back to Python to say that it's started"""
        # print ('PYTHON: GOT SIGNAL BACK FROM METVIEW!')
        self.metview_replied = True

    def read_metview_settings(self, settings_file):
        """Parses the settings file generated by Metview and sets the corresponding env vars"""
        import configparser

        cf = configparser.ConfigParser()
        cf.read(settings_file)
        env_section = cf['Environment']
        for envar in env_section:
            # print('set ', envar.upper(), ' = ', env_section[envar])
            os.environ[envar.upper()] = env_section[envar]
        self.info_section = cf['Info']

    def info(self, key):
        """Returns a piece of Metview information that was not set as an env var"""
        return self.info_section[key]
        
    def store_signal_handlers(self):
        """Stores the set of signal handlers that Metview will override"""
        self.sigint   = signal.getsignal(signal.SIGINT)
        self.sighup   = signal.getsignal(signal.SIGHUP)
        self.sighquit = signal.getsignal(signal.SIGQUIT)
        self.sigterm  = signal.getsignal(signal.SIGTERM)
        self.sigalarm = signal.getsignal(signal.SIGALRM)

    def restore_signal_handlers(self):
        """Restores the set of signal handlers that Metview has overridden"""
        signal.signal(signal.SIGINT, self.sigint)
        signal.signal(signal.SIGHUP, self.sighup)
        signal.signal(signal.SIGQUIT,self.sighquit)
        signal.signal(signal.SIGTERM,self.sigterm)
        signal.signal(signal.SIGALRM,self.sigalarm)


mi = MetviewInvoker()

try:
    ffi = cffi.FFI()
    ffi.cdef(pkgutil.get_data('metview', 'metview.h').decode('ascii'))
    mv_lib = mi.info('METVIEW_LIB')
    # is there a more general way to add to a path to a list of paths?
    os.environ["LD_LIBRARY_PATH"] = mv_lib + ':' + os.environ.get("LD_LIBRARY_PATH", '')

    try:
        # Linux / Unix systems
        lib = ffi.dlopen(os.path.join(mv_lib, 'libMvMacro.so'))
    except OSError:
        # MacOS systems
        lib = ffi.dlopen(os.path.join(mv_lib, 'libMvMacro'))

except Exception as exp:
    print('Error loading Metview/libMvMacro. LD_LIBRARY_PATH=' + os.environ.get("LD_LIBRARY_PATH", ''))
    raise exp


# The C/C++ code behind lib.p_init() will call marsinit(), which overrides various signal handlers. We don't
# necessarily want this when running a Python script - we should use the default Python behaviour
# for handling signals, so we save the current signals before calling p_init() and restore them after.
mi.store_signal_handlers()
lib.p_init()
mi.restore_signal_handlers()



class Value:

    def __init__(self, val_pointer):
        self.val_pointer = val_pointer

    def push(self):
        return self.val_pointer

    # enable a more object-oriented interface, e.g. a = fs.interpolate(10, 29.4)
    def __getattr__(self, fname):
        def call_func_with_self(*args, **kwargs):
            return call(fname, self, *args, **kwargs)
        return call_func_with_self

    # on destruction, ensure that the Macro Value is also destroyed
    def __del__(self):
        try:
            if self.val_pointer is not None and lib is not None:
                lib.p_destroy_value(self.val_pointer)
                self.val_pointer = None
        except Exception as exp:
            print("Could not destroy Metview variable ", self)
            raise exp


class Request(dict, Value):
    verb = "UNKNOWN"

    def __init__(self, req):
        self.val_pointer = None

        # initialise from Python object (dict/Request)
        if isinstance(req, dict):
            self.update(req)
            self.to_metview_style()
            if isinstance(req, Request):
                self.verb = req.verb
                self.val_pointer = req.val_pointer

        # initialise from a Macro pointer
        else:
            Value.__init__(self, req)
            self.verb = string_from_ffi(lib.p_get_req_verb(req))
            n = lib.p_get_req_num_params(req)
            for i in range(0, n):
                param = string_from_ffi(lib.p_get_req_param(req, i))
                raw_val = lib.p_get_req_value(req, param.encode('utf-8'))
                if raw_val != ffi.NULL:
                    val = string_from_ffi(raw_val)
                    self[param] = val
            # self['_MACRO'] = 'BLANK'
            # self['_PATH']  = 'BLANK'

    def __str__(self):
        return "VERB: " + self.verb + super().__str__()

    # translate Python classes into Metview ones where needed
    def to_metview_style(self):
        for k, v in self.items():

            # bool -> on/off
            if isinstance(v, bool):
                conversion_dict = {True: 'on', False: 'off'}
                self[k] = conversion_dict[v]

            # class_ -> class (because 'class' is a Python keyword and cannot be used as a named parameter)
            elif k == 'class_':
                self['class'] = v
                del self['class_']

    def push(self):
        # if we have a pointer to a Metview Value, then use that because it's more
        # complete than the dict
        if self.val_pointer:
            lib.p_push_value(Value.push(self))
        else:
            r = lib.p_new_request(self.verb.encode('utf-8'))

            # to populate a request on the Macro side, we push each
            # value onto its stack, and then tell it to create a new
            # parameter with that name for the request. This allows us to
            # use Macro to handle the addition of complex data types to
            # a request
            for k, v in self.items():
                push_arg(v, 'NONAME')
                lib.p_set_request_value_from_pop(r, k.encode('utf-8'))

            lib.p_push_request(r)

    def __getitem__(self, index):
        # we don't often need integer indexing of requests, but we do in the
        # case of a Display Window object
        if isinstance(index, int):
            return subset(self, python_to_mv_index(index))
        else:
            return subset(self, index)


# def dict_to_request(d, verb='NONE'):
#    # get the verb from the request if not supplied by the caller
#    if verb == 'NONE' and isinstance(d, Request):
#        verb = d.verb
#
#    r = lib.p_new_request(verb.encode('utf-8'))
#    for k, v in d.items():
#        if isinstance(v, (list, tuple)):
#            for v_i in v:
#                v_i = str(v_i).encode('utf-8')
#                lib.p_add_value(r, k.encode('utf-8'), v_i)
#        elif isinstance(v, (Fieldset, Bufr, Geopoints)):
#            lib.p_set_value(r, k.encode('utf-8'), v.push())
#        elif isinstance(v, str):
#            lib.p_set_value(r, k.encode('utf-8'), v.encode('utf-8'))
#        elif isinstance(v, bool):
#            conversion_dict = {True: 'on', False: 'off'}
#            lib.p_set_value(r, k.encode('utf-8'), conversion_dict[v].encode('utf-8'))
#        elif isinstance(v, (int, float)):
#            lib.p_set_value(r, k.encode('utf-8'), str(v).encode('utf-8'))
#        else:
#            lib.p_set_value(r, k.encode('utf-8'), v)
#    return r


# def push_dict(d, verb='NONE'):
#
#    for k, v in d.items():
#        if isinstance(v, (list, tuple)):
#            for v_i in v:
#                v_i = str(v_i).encode('utf-8')
#                lib.p_add_value(r, k.encode('utf-8'), v_i)
#        elif isinstance(v, (Fieldset, Bufr, Geopoints)):
#            lib.p_set_value(r, k.encode('utf-8'), v.push())
#        elif isinstance(v, str):
#            lib.p_set_value(r, k.encode('utf-8'), v.encode('utf-8'))
#        elif isinstance(v, bool):
#            conversion_dict = {True: 'on', False: 'off'}
#            lib.p_set_value(r, k.encode('utf-8'), conversion_dict[v].encode('utf-8'))
#        elif isinstance(v, (int, float)):
#            lib.p_set_value(r, k.encode('utf-8'), str(v).encode('utf-8'))
#        else:
#            lib.p_set_value(r, k.encode('utf-8'), v)
#    return r


def push_bytes(b):
    lib.p_push_string(b)


def push_str(s):
    push_bytes(s.encode('utf-8'))


def push_list(lst):
    # ask Metview to create a new list, then add each element by
    # pusing it onto the stack and asking Metview to pop it off
    # and add it to the list
    mlist = lib.p_new_list(len(lst))
    for i, val in enumerate(lst):
        push_arg(val, 'NONE')
        lib.p_add_value_from_pop_to_list(mlist, i)
    lib.p_push_list(mlist)


def push_date(d):
    lib.p_push_datestring(np.datetime_as_string(d).encode('utf-8'))


def push_datetime(d):
    lib.p_push_datestring(d.isoformat().encode('utf-8'))


def push_datetime_date(d):
    s = d.isoformat() + 'T00:00:00'
    lib.p_push_datestring(s.encode('utf-8'))


def push_vector(npa):

    # convert numpy array to CData
    if npa.dtype == np.float64:
        cffi_buffer = ffi.cast('double*', npa.ctypes.data)
        lib.p_push_vector_from_double_array(cffi_buffer, len(npa), np.nan)
    elif npa.dtype == np.float32:
        cffi_buffer = ffi.cast('float*', npa.ctypes.data)
        lib.p_push_vector_from_float32_array(cffi_buffer, len(npa), np.nan)
    else:
        raise Exception('Only float32 and float64 numPy arrays can be passed to Metview, not ', npa.dtype)


def push_arg(n, name):

    nargs = 1

    if isinstance(n, float):
        lib.p_push_number(n)
    elif isinstance(n, int):
        lib.p_push_number(float(n))
    elif isinstance(n, np.number):
        lib.p_push_number(float(n))
    elif isinstance(n, str):
        push_str(n)
    elif isinstance(n, Request):
        n.push()
    elif isinstance(n, dict):
        Request(n).push()
    elif isinstance(n, Fieldset):
        lib.p_push_value(n.push())
    elif isinstance(n, Bufr):
        lib.p_push_value(n.push())
    elif isinstance(n, Geopoints):
        lib.p_push_value(n.push())
    elif isinstance(n, NetCDF):
        lib.p_push_value(n.push())
    elif isinstance(n, np.datetime64):
        push_date(n)
    elif isinstance(n, datetime.datetime):
        push_datetime(n)
    elif isinstance(n, datetime.date):
        push_datetime_date(n)
    elif isinstance(n, (list, tuple)):
        push_list(n)
    elif isinstance(n, np.ndarray):
        push_vector(n)
    elif isinstance(n, Odb):
        lib.p_push_value(n.push())
    elif isinstance(n, Table):
        lib.p_push_value(n.push())
    elif isinstance(n, GeopointSet):
        lib.p_push_value(n.push())
    elif n is None:
        lib.p_push_nil()
    else:
        raise TypeError('Cannot push this type of argument to Metview: ', builtins.type(n))

    return nargs


def dict_to_pushed_args(d):

    # push each key and value onto the argument stack
    for k, v in d.items():
        push_str(k)
        push_arg(v, 'NONE')

    return 2 * len(d)  # return the number of arguments generated


class FileBackedValue(Value):

    def __init__(self, val_pointer):
        Value.__init__(self, val_pointer)

    def url(self):
        # ask Metview for the file relating to this data (Metview will write it if necessary)
        return string_from_ffi(lib.p_data_path(self.val_pointer))


class FileBackedValueWithOperators(FileBackedValue):

    def __init__(self, val_pointer):
        FileBackedValue.__init__(self, val_pointer)

    def __add__(self, other):
        return add(self, other)

    def __sub__(self, other):
        return sub(self, other)

    def __mul__(self, other):
        return prod(self, other)

    def __truediv__(self, other):
        return div(self, other)

    def __pow__(self, other):
        return power(self, other)

    def __ge__(self, other):
        return greater_equal_than(self, other)

    def __gt__(self, other):
        return greater_than(self, other)

    def __le__(self, other):
        return lower_equal_than(self, other)

    def __lt__(self, other):
        return lower_than(self, other)



class ContainerValue(Value):
    def __init__(self, val_pointer, macro_index_base, element_type):
        Value.__init__(self, val_pointer)
        self.idx = 0
        self.macro_index_base = macro_index_base
        self.element_type = element_type # the type of elements that the container contains

    def __len__(self):
        return int(count(self))

    def __getitem__(self, index):
        return subset(self, index + self.macro_index_base) # convert from 0-based indexing

    def __setitem__(self, index, value):
        if (isinstance(value, self.element_type)):
            lib.p_set_subvalue(self.val_pointer, index+self.macro_index_base, value.val_pointer)
        else:
            raise Exception('Cannot assign ', value, ' as element of ', self)

    def __iter__(self):
        return self

    def __next__(self):
        if self.idx >= self.__len__():
            self.idx = 0
            raise StopIteration
        else:
            self.idx += 1
            return self.__getitem__(self.idx-1)



class Fieldset(FileBackedValueWithOperators, ContainerValue):

    def __init__(self, val_pointer):
        FileBackedValue.__init__(self, val_pointer)
        ContainerValue.__init__(self, val_pointer, 1, Fieldset)

    def to_dataset(self):
        # soft dependency on cfgrib
        try:
            from cfgrib import xarray_store
        except ImportError:
            print("Package xarray_grib not found. Try running 'pip install xarray_grib'.")
            raise
        dataset = xarray_store.open_dataset(self.url())
        return dataset


class Bufr(FileBackedValue):

    def __init__(self, val_pointer):
        FileBackedValue.__init__(self, val_pointer)


class Geopoints(FileBackedValueWithOperators, ContainerValue):

    def __init__(self, val_pointer):
        FileBackedValueWithOperators.__init__(self, val_pointer)
        ContainerValue.__init__(self, val_pointer, 0, None)

    def to_dataframe(self):
        try:
            import pandas as pd
        except ImportError:
            print("Package pandas not found. Try running 'pip install pandas'.")
            raise

        tp = self.dtype()

        pddict = {'latitude'  : self.latitudes(),
                  'longitude' : self.longitudes(),
                  'value'     : self.values()}

        if tp in ('standard', 'xy_vector', 'polar_vector', 'standard_string'):
            pddict['level'] = self.levels()
            pddict['date']  = self.dates()

        if tp in ('xy_vector', 'polar_vector'):
            pddict['value2'] = self.value2s()

        df = pd.DataFrame(pddict)
        return df


class NetCDF(FileBackedValueWithOperators):
    def __init__(self, val_pointer):
        FileBackedValueWithOperators.__init__(self, val_pointer)


class Odb(FileBackedValue):

    def __init__(self, val_pointer):
        FileBackedValue.__init__(self, val_pointer)

    def to_dataframe(self):
        try:
            import pandas as pd
        except ImportError:
            print("Package pandas not found. Try running 'pip install pandas'.")
            raise

        cols = self.columns()
        pddict = {}

        for col in cols:
            pddict[col] = self.values(col)

        df = pd.DataFrame(pddict)
        return df


class Table(FileBackedValue):

    def __init__(self, val_pointer):
        FileBackedValue.__init__(self, val_pointer)


class GeopointSet(FileBackedValueWithOperators, ContainerValue):

    def __init__(self, val_pointer):
        FileBackedValueWithOperators.__init__(self, val_pointer)
        ContainerValue.__init__(self, val_pointer, 1, Geopoints)


def list_from_metview(mlist):

    result = []
    n = lib.p_list_count(mlist)
    all_vectors = True
    for i in range(0, n):
        mval = lib.p_list_element_as_value(mlist, i)
        v = value_from_metview(mval)
        if all_vectors and not isinstance(v, np.ndarray):
            all_vectors = False
        result.append(v)

    # if this is a list of vectors, then create a 2-D numPy array
    if all_vectors and n > 0:
        result = np.stack(result, axis=0)

    return result


def datestring_from_metview(mdate):

    dt = datetime.datetime.strptime(mdate, "%Y-%m-%dT%H:%M:%S")
    return dt


def vector_from_metview(vec):

    n = lib.p_vector_count(vec)
    s = lib.p_vector_elem_size(vec)

    if s == 4:
        nptype = np.float32
        b = lib.p_vector_float32_array(vec)
    elif s == 8:
        nptype = np.float64
        b = lib.p_vector_double_array(vec)
    else:
        raise Exception('Metview vector data type cannot be handled: ', s)

    bsize = n*s
    c_buffer = ffi.buffer(b, bsize)
    np_array = np.frombuffer(c_buffer, dtype=nptype)
    return np_array


# we can actually get these from Metview, but for testing we just have a dict
# service_function_verbs = {
#     'retrieve': 'RETRIEVE',
#     'mcoast': 'MCOAST',
#     'mcont': 'MCONT',
#     'mobs': 'MOBS',
#     'msymb': 'MSYMB',
#     'read': 'READ',
#     'geoview': 'GEOVIEW',
#     'mtext': 'MTEXT',
#     'ps_output': 'PS_OUTPUT',
#     'obsfilter': 'OBSFILTER',
#     'filter': 'FILTER'
# }


def _call_function(mfname, *args, **kwargs):

    nargs = 0

    for n in args:
        actual_n_args = push_arg(n, mfname)
        nargs += actual_n_args

    merged_dict = {}
    merged_dict.update(kwargs)
    if len(merged_dict) > 0:
        dn = dict_to_pushed_args(Request(merged_dict))
        nargs += dn

    lib.p_call_function(mfname.encode('utf-8'), nargs)


def value_from_metview(val):
    rt = lib.p_value_type(val)

    # Number
    if rt == 0:
        return lib.p_value_as_number(val)
    # String
    elif rt == 1:
        return string_from_ffi(lib.p_value_as_string(val))
    # Fieldset
    elif rt == 2:
        return Fieldset(val)
    # Request dictionary
    elif rt == 3:
        return Request(val)
    # BUFR
    elif rt == 4:
        return Bufr(val)
    # Geopoints
    elif rt == 5:
        return Geopoints(val)
    # list
    elif rt == 6:
        return list_from_metview(lib.p_value_as_list(val))
    # netCDF
    elif rt == 7:
        return NetCDF(val)
    elif rt == 8:
        return None
    elif rt == 9:
        err_msg = string_from_ffi(lib.p_error_message(val))
        raise Exception('Metview error: ' + err_msg)
    # date
    elif rt == 10:
        return datestring_from_metview(string_from_ffi(lib.p_value_as_datestring(val)))
    elif rt == 11:
        return vector_from_metview(lib.p_value_as_vector(val, np.nan))
    # Odb
    elif rt == 12:
        return Odb(val)
    # Table
    elif rt == 13:
        return Table(val)
    # Geopointset
    elif rt == 14:
        return GeopointSet(val)

    else:
        raise Exception('value_from_metview got an unhandled return type: ' + str(rt))


def make(mfname):

    def wrapped(*args, **kwargs):
        err = _call_function(mfname, *args, **kwargs)
        if err:
            pass  # throw Exceception

        val = lib.p_result_as_value()
        return value_from_metview(val)

    return wrapped


def bind_functions(namespace, module_name=None):
    """Add to the module globals all metview functions except operators like: +, &, etc."""
    for metview_name in make('dictionary')():
        if metview_name.isidentifier():
            python_name = metview_name
            # NOTE: we append a '_' to metview functions that clash with python reserved keywords
            #   as they cannot be used as identifiers, for example: 'in' -> 'in_'
            if keyword.iskeyword(metview_name):
                python_name += '_'
            python_func = make(metview_name)
            python_func.__name__ = python_name
            python_func.__qualname__ = python_name
            if module_name:
                python_func.__module__ = module_name
            namespace[python_name] = python_func
        #else:
        #    print('metview function %r not bound to python' % metview_name)
    # add the 'mvl' functions, which are written in Macro and therefore not
    # listed by the dictionary() function
    for f in ['mvl_ml2hPa', 'mvl_create_netcdf_2d', 'mvl_flextra_etadot', 'mvl_geocircle',
              'mvl_geoline', 'mvl_geopotential_on_ml', 'mvl_mxn_subframes', 'mvl_plot_scm_data',
              'mvl_regular_layout', 'mvl_regular_layout_area']:
        namespace[f] = make(f)

    # HACK: some fuctions are missing from the 'dictionary' call.
    namespace['neg'] = make('neg')
    namespace['nil'] = make('nil')
    # override some functions that need special treatment
    # FIXME: this needs to be more structured
    namespace['plot'] = plot
    namespace['setoutput'] = setoutput


# some explicit bindings are used here
add = make('+')
call = make('call')
count = make('count')
div = make('/')
filter = make('filter')
greater_equal_than = make('>=')
greater_than = make('>')
lower_equal_than = make('<=')
lower_than = make('<')
merge = make('&')
met_plot = make('plot')
nil = make('nil')
png_output = make('png_output')
power = make('^')
prod = make('*')
ps_output = make('ps_output')
read = make('read')
met_setoutput = make('setoutput')
sub = make('-')
subset = make('[]')


# experimental class to facilitate calling an arbitrary Macro function
# function callers are created on-demand
# e.g. mv.mf.nearest_gridpoint_info(grib, 10, 20)
class MF():

    def __init__(self):
        self.func_map = {}

    def __getattr__(self, fname):
        if fname in self.func_map:
            return self.func_map[fname]
        else:
            f = make(fname)
            self.func_map[fname] = f
            return f

    # required for IDEs to list the available functions
    def __dir__(self):
        macro_dict = make('dictionary')
        all_funcs = macro_dict()
        most_funcs = [f for f in all_funcs if len(f) > 1]
        return most_funcs


mf = MF()


# for x in range(350):
#     exec("uppercase = make('uppercase')")


class Plot():

    def __init__(self):
        self.plot_to_jupyter = False

    def __call__(self, *args, **kwargs):
        if self.plot_to_jupyter:
            f, tmp = tempfile.mkstemp(".png")
            os.close(f)

            base, ext = os.path.splitext(tmp)

            met_setoutput(png_output(output_name=base, output_name_first_page_number='off'))
            met_plot(*args)

            image = Image(tmp)
            os.unlink(tmp)
            return image
        else:
            map_outputs = {
                'png': png_output,
                'ps': ps_output,
            }
            if 'output_type' in kwargs:
                output_function = map_outputs[kwargs['output_type'].lower()]
                kwargs.pop('output_type')
                met_plot(output_function(kwargs), *args)
            else:
                met_plot(*args)
            # the Macro plot command returns an empty definition, but
            # None is better for Python
            return None


plot = Plot()


# On a test system, importing IPython took approx 0.5 seconds, so to avoid that hit
# under most circumstances, we only import it when the user asks for Jupyter
# functionality. Since this occurs within a function, we need a little trickery to
# get the IPython functions into the global namespace so that the plot object can use them
def setoutput(*args):
    if 'jupyter' in args:
        try:
            global Image
            global get_ipython
            IPython = __import__('IPython', globals(), locals())
            Image = IPython.display.Image
            get_ipython = IPython.get_ipython
        except ImportError as imperr:
            print('Could not import IPython module - plotting to Jupyter will not work')
            raise imperr

        # test whether we're in the Jupyter environment
        if get_ipython() is not None:
            plot.plot_to_jupyter = True
        else:
            print("ERROR: setoutput('jupyter') was set, but we are not in a Jupyter environment")
            raise(Exception('Could not set output to jupyter'))
    else:
        plot.plot_to_jupyter = False
        met_setoutput(*args)


# perform a MARS retrieval
# - defined a request
# - set waitmode to 1 to force synchronisation
# - the return is a path to a temporary file, so copy it before end of script
# req = { 'PARAM' : 't',
#         'LEVELIST' : ['1000', '500'],
#         'GRID' : ['2', '2']}
# waitmode(1)
# g = retrieve(req)
# print(g)
# copyfile(g, './result.grib')
