#!/usr/bin/env python3

import logging
import argparse
import zmq
import sys
import pickle


from ipyparallel.serialize import serialize_object
from parsl.app.errors import RemoteExceptionWrapper

from funcx import set_file_logger
from funcx.serialize import FuncXSerializer

# . 

class FuncXWorker(object):
    """ The FuncX worker
    Parameters
    ----------

    worker_id : str
     Worker id string

    address : str
     Address at which the manager might be reached. This is usually 127.0.0.1

    port : int
     Port at which the manager can be reached

    logdir : str
     Logging directory

    debug : Bool
     Enables debug logging


    Funcx worker will use the REP sockets to:
         task = recv ()
         result = execute(task)
         send(result)


    """

    def __init__(self, worker_id, address, port, logdir, debug=False, worker_type='RAW'):

        self.worker_id = worker_id
        self.address = address
        self.port = port
        self.logdir = logdir
        self.debug = debug
        self.worker_type = worker_type
        self.serializer = FuncXSerializer()
        self.serialize = self.serializer.serialize
        self.deserialize = self.serializer.deserialize

        global logger
        logger = set_file_logger('{}/funcx_worker_{}.log'.format(logdir, worker_id),
                                 name="worker_log",
                                 level=logging.DEBUG if debug else logging.INFO)

        logger.info('Initializing worker {}'.format(worker_id))
        logger.info('Worker is of type: {}'.format(worker_type))

        if debug:
            logger.debug('Debug logging enabled')

        self.context = zmq.Context()
        self.poller = zmq.Poller()
        self.identity = worker_id.encode()

        self.task_socket = self.context.socket(zmq.DEALER)
        self.task_socket.setsockopt(zmq.IDENTITY, self.identity)

        logger.info('Trying to connect to : tcp://{}:{}'.format(self.address, self.port))
        self.task_socket.connect('tcp://{}:{}'.format(self.address, self.port))
        self.poller.register(self.task_socket, zmq.POLLIN)

    def registration_message(self):
        return {'worker_id': self.worker_id,
                'worker_type': self.worker_type}

    def start(self):

        logger.info("Starting worker")

        result = self.registration_message()
        task_type = b'REGISTER'

        while True:

            logger.debug("Sending result")
            # TODO : Swap for our serialization methods
            self.task_socket.send_multipart([task_type, # Byte encoded
                                             pickle.dumps(result)])

            if task_type == b'WRKR_DIE':
                logger.info("*** WORKER {} ABOUT TO DIE ***".format(self.worker_id))
                exit()  # Kill the worker after accepting death in message to manager. 

            logger.debug("Waiting for task")
            p_task_id, msg = self.task_socket.recv_multipart()
            task_id = pickle.loads(p_task_id)
            logger.debug("Received task_id:{} with task:{}".format(task_id, msg))

            if msg == b"KILL":  # TODO: This WAS task type...
                logger.info("[KILL] -- Worker KILL message received! ")
                task_type = b'WRKR_DIE'
                result = None
                continue

            logger.debug("Executing task...")

            try:
                result = self.execute_task(msg)
                logger.debug("Executed result: {}".format(result))
                serialized_result = serialize_object(result)
            except Exception:
                logger.exception("Caught an exception {}")
                result_package = {'task_id': task_id, 'exception': serialize_object(RemoteExceptionWrapper(*sys.exc_info()))}
            else:
                logger.debug("Execution completed without exception")
                result_package = {'task_id': task_id, 'result': serialized_result}

            # TODO: Change this to serialize_object to match IX?
            result = result_package
            task_type = b'TASK_RET'

    def execute_task(self, message):
        """Deserialize the buffer and execute the task.

        Returns the result or throws exception.
        """

        logger.debug("Inside execute_task function")
        user_ns = locals()
        user_ns.update({'__builtins__': __builtins__})

        logger.info("Trying to pickle load the message {}".format(message))
        decoded = message.decode()
        f, args, kwargs = self.serializer.unpack_and_deserialize(decoded)
        logger.debug("Message unpacked")

        # We might need to look into callability of the function from itself
        # since we change it's name in the new namespace
        """
        prefix = "parsl_"
        fname = prefix + "f"
        argname = prefix + "args"
        kwargname = prefix + "kwargs"
        resultname = prefix + "result"

        user_ns.update({fname: f,
                        argname: args,
                        kwargname: kwargs,
                        resultname: resultname})

        logger.debug("Namespace updated")

        code = "{0} = {1}(*{2}, **{3})".format(resultname, fname,
                                               argname, kwargname)

        try:
            exec(code, user_ns, user_ns)

        except Exception as e:
            raise e

        else:
            return user_ns.get(resultname)

        """
        return f(*args, **kwargs)


def cli_run():
    parser = argparse.ArgumentParser()
    parser.add_argument("-w", "--worker_id", required=True,
                        help="ID of worker from process_worker_pool")
    parser.add_argument("-t", "--type", required=False,
                        help="Container type of worker", default="RAW")
    parser.add_argument("-a", "--address", required=True,
                        help="Address for the manager, eg X,Y,")
    parser.add_argument("-p", "--port", required=True,
                        help="Internal port at which the worker connects to the manager")
    parser.add_argument("--logdir", required=True,
                        help="Directory path where worker log files written")
    parser.add_argument("-d", "--debug", action='store_true',
                        help="Directory path where worker log files written")

    args = parser.parse_args()
    worker = FuncXWorker(args.worker_id,
                         args.address,
                         int(args.port),
                         args.logdir,
                         worker_type=args.type,
                         debug=args.debug, )
    worker.start()
    return


if __name__ == "__main__":
    cli_run()
