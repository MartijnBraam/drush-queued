import argparse
import pymysql
import urllib.parse
import logging
import subprocess
import asyncio
from aiohttp.web import Application, Response
from aiohttp_sse import EventSourceResponse

# Parse command line arguments
parser = argparse.ArgumentParser(description="Drush queue runner")
group = parser.add_mutually_exclusive_group()
group.add_argument('--dburi', help="Database uri")
group.add_argument('--database', help="Database to use")
parser.add_argument('--myconf', help="Mysql my.conf file with connection settings")
parser.add_argument('--loglevel', help="Set the output log level", choices=['debug', 'info', 'warning', 'error'],
                    default='warning')
parser.add_argument('--interval', help="The interval in seconds to check for new tasks", type=int, default=1)
parser.add_argument('--eventproxy', help="Set the url for a sse-proxy server to notify queue changes to the browser")
parser.add_argument('--eventsource', help="Run an eventsource server on the specified port", type=int)
args = parser.parse_args()

# Import requirements for the eventproxy
if args.eventproxy:
    import requests

# Set up the logger
if args.loglevel == 'debug':
    logging.basicConfig(level=logging.DEBUG)
elif args.loglevel == 'info':
    logging.basicConfig(level=logging.INFO)
elif args.loglevel == 'warning':
    logging.basicConfig(level=logging.WARN)
elif args.loglevel == 'error':
    logging.basicConfig(level=logging.ERROR)

# Create the connection options from the command line arguments
connect_options = {}
if args.dburi:
    urllib.parse.uses_netloc.append('mysql')
    parsed = urllib.parse.urlparse(args.dburi)
    if parsed[0] != 'mysql':
        logging.error('Invalid database uri. schema {} is not supported'.format(parsed[0]))
        logging.error('Use a uri in the format: mysql://username:password@hostname/database')

    connect_options = {
        'host': parsed.hostname,
        'user': parsed.username,
        'passwd': parsed.password,
        'db': parsed.path[1:]
    }
elif args.database:
    connect_options['db'] = args.database
    if args.myconf:
        connect_options['read_default_file'] = args.myconf
else:
    print("Specify --database or --dburi to use this tool")
    exit(1)

# Define variable to hold all the eventsource sockets
sockets = set()


@asyncio.coroutine
def drush_queue_runner(loop):
    while True:
        logging.info('Connecting to database')
        try:
            database = pymysql.connect(connect_timeout=10, **connect_options)
            database.autocommit(True)
        except Exception as e:
            logging.error(str(e))
            logging.error('retrying in 5 seconds')
            yield from asyncio.sleep(5)
            continue
        logging.info('Connected')

        try:
            # Start the task loop
            while True:
                yield from asyncio.sleep(args.interval)
                cursor = database.cursor()
                try:
                    cursor.execute('SELECT t.nid '
                                   'FROM hosting_task AS t '
                                   'INNER JOIN node AS n '
                                   'ON t.vid = n.vid '
                                   'WHERE t.task_status = 0 '
                                   'GROUP BY t.rid '
                                   'ORDER BY n.changed, n.nid ASC')
                    result = cursor.fetchall()
                finally:
                    cursor.close()

                if result:
                    logging.info('New tasks')
                    nids = [row[0] for row in result]
                    for nid in nids:
                        yield from asyncio.sleep(0.1)
                        logging.info("Executing task {}".format(nid))
                        try:
                            proc = yield from asyncio.create_subprocess_exec('drush', '@hostmaster', 'hosting-task', str(nid),
                                                                  loop=loop)
                            if args.eventproxy:
                                message = {
                                    'type': 'event',
                                    'name': 'task-start',
                                    'data': str(nid)
                                }
                                requests.post(args.eventproxy, json=message)
                            if args.eventsource:
                                broadcast_task_start(nid)
                            yield from proc.wait()
                            logging.info('Task successful')
                        except subprocess.CalledProcessError:
                            logging.error('Executing task {} failed'.format(nid))
                        if args.eventproxy:
                            message = {
                                'type': 'event',
                                'name': 'task-finished',
                                'data': str(nid)
                            }
                            requests.post(args.eventproxy, json=message)
                        if args.eventsource:
                            broadcast_task_refresh(nid)

        except BrokenPipeError as e:
            logging.error(str(e))
        except pymysql.OperationalError as e:
            logging.error(str(e))


def broadcast_task_refresh(nid):
    global sockets
    for eventsource_client in sockets:
        eventsource_client.send(str(nid), event="task-finished")

def broadcast_task_start(nid):
    global sockets
    for eventsource_client in sockets:
        eventsource_client.send(str(nid), event="task-start")


@asyncio.coroutine
def eventsource(request):
    response = EventSourceResponse()
    response.start(request)

    global sockets
    sockets.add(response)
    logging.debug('User joined eventsource. (now {} clients)'.format(len(sockets)))

    try:
        yield from response.wait()
    except Exception as e:
        sockets.remove(response)
        logging.debug("User left eventsource ({} clients left)".format(len(sockets)))
        raise e

    return response


@asyncio.coroutine
def webserver(loop):
    app = Application(loop=loop)

    app.router.add_route('GET', '/eventsource/', eventsource)

    handler = app.make_handler()
    srv = yield from loop.create_server(handler, '127.0.0.1', args.eventsource)
    logging.info("Eventsource started at http://127.0.0.1:{}".format(args.eventsource))
    return srv, handler


loop = asyncio.get_event_loop()
asyncio.async(drush_queue_runner(loop))
if args.eventsource:
    asyncio.async(webserver(loop))

loop.run_forever()
