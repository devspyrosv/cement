"""
The Logging Extension provides log handling based on
the standard :py:class:`logging.Logger`, and is the default log
handler used by Cement.

Requirements
------------

 * No external dependencies.

Configuration
-------------

This extension honors the following configuration settings from the config
section ``log.logging``:

    * level
    * file
    * to_console
    * rotate
    * max_bytes
    * max_files


A sample config section (in any config file) might look like:

.. code-block:: text

    [log.logging]
    file = /path/to/config/file
    level = info
    to_console = true
    rotate = true
    max_bytes = 512000
    max_files = 4

Usage
-----

.. code-block:: python

    from cement import App

    with App('myapp') as app:
        app.log.info("This is an info message")
        app.log.warning("This is an warning message")
        app.log.error("This is an error message")
        app.log.fatal("This is a fatal message")
        app.log.debug("This is a debug message")


Toggle Log Level Via Commandline Argument
-----------------------------------------

This extension adds a commandline argument to toggle the log level on the fly:

.. code-block:: text

    $ python myapp.py --help
    usage: myapp [-h] [--debug] [--quiet] [-l {info,warning,error,debug,fatal}]

    optional arguments:
      -h, --help            show this help message and exit
      --debug               full application debug mode
      --quiet               suppress all output
      -l {info,warning,error,debug,fatal}
                            logging level


    $ python myapp.py
    INFO: This is an info message
    WARNING: This is an warning message
    ERROR: This is an error message
    CRITICAL: This is a fatal message

    $ python myapp.py -l error
    ERROR: This is an error message
    CRITICAL: This is a fatal message


**Disabling The Commandline Argument**

If no command line argument is desired, you can disable it by setting the
``App.Meta.meta_defaults`` for the ``log.logging`` handler:

.. code-block:: python

    from cement import App, init_defaults

    meta = init_defaults('log.logging')
    meta['log.logging']['log_level_argument'] = None

    class MyApp(App):
        class Meta:
            label = 'myapp'
            meta_defaults = meta

"""

import os
import logging
from ..core import log
from ..utils.misc import is_true, minimal_logger
from ..utils import fs

LOG = minimal_logger(__name__)

try:                                        # pragma: no cover
    NullHandler = logging.NullHandler       # pragma: no cover
except AttributeError as e:                 # pragma: no cover
    # Not supported on Python < 3.1/2.7     # pragma: no cover
    class NullHandler(logging.Handler):     # pragma: no cover

        def handle(self, record):           # pragma: no cover
            pass                            # pragma: no cover
            # pragma: no cover

        def emit(self, record):             # pragma: no cover
            pass                            # pragma: no cover
            # pragma: no cover

        def createLock(self):               # pragma: no cover
            self.lock = None                # pragma: no cover


class LoggingLogHandler(log.LogHandler):

    """
    This class is an implementation of the :ref:`Log <cement.core.log>`
    interface, and sets up the logging facility using the standard Python
    `logging <http://docs.python.org/library/logging.html>`_ module.

    """

    class Meta:

        """Handler meta-data."""

        #: The string identifier of this handler.
        label = 'logging'

        #: The logging namespace.
        #:
        #: Note: Although Meta.namespace defaults to None, Cement will set
        #: this to the application label (App.Meta.label) if not set
        #: during setup.
        namespace = None

        #: Class to use as the formatter
        formatter_class = logging.Formatter

        #: The logging format for the file logger.
        file_format = "%(asctime)s (%(levelname)s) %(namespace)s : " + \
                      "%(message)s"

        #: The logging format for the consoler logger.
        console_format = "%(levelname)s: %(message)s"

        #: The logging format for both file and console if ``debug==True``.
        debug_format = "%(asctime)s (%(levelname)s) %(namespace)s : " + \
                       "%(message)s"

        #: List of logger namespaces to clear.  Useful when imported software
        #: also sets up logging and you end up with duplicate log entries.
        #:
        #: Changes in Cement 2.1.3.  Previous versions only supported
        #: `clear_loggers` as a boolean, but did fully support clearing
        #: non-app logging namespaces.
        clear_loggers = []

        #: The default configuration dictionary to populate the ``log``
        #: section.
        config_defaults = dict(
            file=None,
            level='INFO',
            to_console=True,
            rotate=False,
            max_bytes=512000,
            max_files=4,
        )

        #: The arguments to use for the cli options.  If a log-level argument
        #: is not wanted, set to `None`
        log_level_argument = ['-l']

        #: The help description for the log level argument
        log_level_argument_help = 'logging level'

    levels = ['INFO', 'WARNING', 'ERROR', 'DEBUG', 'FATAL']

    def __init__(self, *args, **kw):
        super(LoggingLogHandler, self).__init__(*args, **kw)
        self.app = None

    def _setup(self, app_obj):
        super(LoggingLogHandler, self)._setup(app_obj)
        if self._meta.namespace is None:
            self._meta.namespace = "%s" % self.app._meta.label

        self.backend = logging.getLogger("cement:app:%s" %
                                         self._meta.namespace)

        # hack for application debugging
        if is_true(self.app._meta.debug):
            self.app.config.set(self._meta.config_section, 'level', 'DEBUG')

        level = self.app.config.get(self._meta.config_section, 'level')
        self.set_level(level)

        LOG.debug("logging initialized for '%s' using %s" %
                  (self._meta.namespace, self.__class__.__name__))

    def set_level(self, level):
        """
        Set the log level.  Must be one of the log levels configured in
        self.levels which are
        ``['INFO', 'WARNING', 'ERROR', 'DEBUG', 'FATAL']``.

        :param level: The log level to set.

        """
        self.clear_loggers(self._meta.namespace)
        for namespace in self._meta.clear_loggers:
            self.clear_loggers(namespace)

        level = level.upper()
        if level not in self.levels:
            level = 'INFO'
        level = getattr(logging, level.upper())

        self.backend.setLevel(level)

        # console
        self._setup_console_log()

        # file
        self._setup_file_log()

    def get_level(self):
        """Returns the current log level."""
        return logging.getLevelName(self.backend.level)

    def clear_loggers(self, namespace):
        """Clear any previously configured loggers for ``namespace``."""

        for i in logging.getLogger("cement:app:%s" % namespace).handlers:
            logging.getLogger("cement:app:%s" % namespace).removeHandler(i)

        self.backend = logging.getLogger("cement:app:%s" % namespace)

    def _get_console_format(self):
        if self.get_level() == logging.getLevelName(logging.DEBUG):
            format = self._meta.debug_format
        else:
            format = self._meta.console_format

        return format

    def _get_file_format(self):
        if self.get_level() == logging.getLevelName(logging.DEBUG):
            format = self._meta.debug_format
        else:
            format = self._meta.file_format

        return format

    def _get_file_formatter(self, format):
        return self._meta.formatter_class(format)

    def _get_console_formatter(self, format):
        return self._meta.formatter_class(format)

    def _setup_console_log(self):
        """Add a console log handler."""
        namespace = self._meta.namespace
        to_console = self.app.config.get(self._meta.config_section,
                                         'to_console')
        if is_true(to_console):
            console_handler = logging.StreamHandler()
            format = self._get_console_format()
            formatter = self._get_console_formatter(format)
            console_handler.setFormatter(formatter)
            console_handler.setLevel(getattr(logging, self.get_level()))
        else:
            console_handler = NullHandler()

        # FIXME: self._clear_loggers() should be preventing this but its not!
        for i in logging.getLogger("cement:app:%s" % namespace).handlers:
            if isinstance(i, logging.StreamHandler):
                self.backend.removeHandler(i)

        self.backend.addHandler(console_handler)

    def _setup_file_log(self):
        """Add a file log handler."""

        namespace = self._meta.namespace
        file_path = self.app.config.get(self._meta.config_section, 'file')
        rotate = self.app.config.get(self._meta.config_section, 'rotate')
        max_bytes = self.app.config.get(self._meta.config_section,
                                        'max_bytes')
        max_files = self.app.config.get(self._meta.config_section,
                                        'max_files')
        if file_path:
            file_path = fs.abspath(file_path)
            log_dir = os.path.dirname(file_path)
            if not os.path.exists(log_dir):
                os.makedirs(log_dir)

            if rotate:
                from logging.handlers import RotatingFileHandler
                file_handler = RotatingFileHandler(
                    file_path,
                    maxBytes=int(max_bytes),
                    backupCount=int(max_files),
                )
            else:
                from logging import FileHandler
                file_handler = FileHandler(file_path)

            format = self._get_file_format()
            formatter = self._get_file_formatter(format)
            file_handler.setFormatter(formatter)
            file_handler.setLevel(getattr(logging, self.get_level()))
        else:
            file_handler = NullHandler()

        # FIXME: self._clear_loggers() should be preventing this but its not!
        for i in logging.getLogger("cement:app:%s" % namespace).handlers:
            if isinstance(i, file_handler.__class__):   # pragma: nocover
                self.backend.removeHandler(i)           # pragma: nocover

        self.backend.addHandler(file_handler)

    def _get_logging_kwargs(self, namespace, **kw):
        if namespace is None:
            namespace = self._meta.namespace

        if 'extra' in kw.keys() and 'namespace' in kw['extra'].keys():
            pass
        elif 'extra' in kw.keys() and 'namespace' not in kw['extra'].keys():
            kw['extra']['namespace'] = namespace
        else:
            kw['extra'] = dict(namespace=namespace)

        return kw

    def info(self, msg, namespace=None, **kw):
        """
        Log to the INFO facility.

        Args:
            msg (str): The message to log.

        Keyword Args:
            namespace (str): A log prefix, generally the module ``__name__``
                that the log is coming from.  Will default to
                ``self._meta.namespace`` if none is passed.

        Other Parameters:
            kwargs: Keyword arguments are passed on to the backend logging
                system.

        """
        kwargs = self._get_logging_kwargs(namespace, **kw)
        self.backend.info(msg, **kwargs)

    def warning(self, msg, namespace=None, **kw):
        """
        Log to the WARNING facility.

        Args:
            msg (str): The message to log.

        Keyword Args:
            namespace (str): A log prefix, generally the module ``__name__``
                that the log is coming from.  Will default to
                ``self._meta.namespace`` if none is passed.

        Other Parameters:
            kwargs: Keyword arguments are passed on to the backend logging
                system.

        """
        kwargs = self._get_logging_kwargs(namespace, **kw)
        self.backend.warning(msg, **kwargs)

    def error(self, msg, namespace=None, **kw):
        """
        Log to the ERROR facility.

        :Args:
            msg (str): The message to log.

        Keyword Args:
            namespace (str): A log prefix, generally the module ``__name__``
                that the log is coming from.  Will default to
                ``self._meta.namespace`` if none is passed.

        Other Parameters:
            kwargs: Keyword arguments are passed on to the backend logging
                system.

        """
        kwargs = self._get_logging_kwargs(namespace, **kw)
        self.backend.error(msg, **kwargs)

    def fatal(self, msg, namespace=None, **kw):
        """
        Log to the FATAL (aka CRITICAL) facility.

        Args:
            msg (str): The message to log.

        Keyword Args:
            namespace (str): A log prefix, generally the module ``__name__``
                that the log is coming from.  Will default to
                ``self._meta.namespace`` if none is passed.

        Other Parameters:
            kwargs: Keyword arguments are passed on to the backend logging
                system.

        """
        kwargs = self._get_logging_kwargs(namespace, **kw)
        self.backend.fatal(msg, **kwargs)

    def debug(self, msg, namespace=None, **kw):
        """
        Log to the DEBUG facility.

        Args:
            msg (str): The message to log.

        Keyword Args:
            namespace (str): A log prefix, generally the module ``__name__``
                that the log is coming from.  Will default to
                ``self._meta.namespace`` if none is passed.

        Other Parameters:
            kwargs: Keyword arguments are passed on to the backend logging
                system.

        """
        kwargs = self._get_logging_kwargs(namespace, **kw)
        self.backend.debug(msg, **kwargs)


def add_logging_arguments(app):
    if app.log._meta.log_level_argument is not None:
        app.args.add_argument(*app.log._meta.log_level_argument,
                              dest='log_logging_level',
                              help=app.log._meta.log_level_argument_help,
                              choices=[x.lower() for x in app.log.levels])


def handle_logging_arguments(app):
    if hasattr(app.pargs, 'log_logging_level'):
        if app.pargs.log_logging_level is not None:
            app.log.set_level(app.pargs.log_logging_level)
        if app.pargs.log_logging_level in ['debug', 'DEBUG']:
            app._meta.debug = True


def load(app):
    app.handler.register(LoggingLogHandler)
    app.hook.register('pre_argument_parsing', add_logging_arguments)
    app.hook.register('post_argument_parsing', handle_logging_arguments)
