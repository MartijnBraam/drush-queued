# Drush Queued for aegir

This is a python script that replaces the `drush hosting-queued` command. It waits for new tasks in the Aegir task queue
 and executes them through drush as a seperate process. This prevents memory leaks in drush and the tasks from crashing
 the daemon.
 
# Installation and usage

Clone the repository somewhere and start the script with:

```bash
$ python3 drushqueued --dburi mysql://a:b@localhost/theaegirdatabase
```

Or to use the login information in `/etc/my.conf`

```bash
$ python3 drushqueued --database theaegirdatabase

# The my.conf for aegir
$ python3 drushqueued --database aegir --myconf /opt/aegir/my.conf
```

# Options

## Verbosity

The default verbosity is WARNING. Use `--loglevel` to change it:

```bash
$ python3 drushqueued --database theaegirdatabase --loglevel info
```

## Interval

By default the script checks for new tasks every second. You can change it with the `--interval` option

```bash
$ python3 drushqueued --database theaegirdatabase --interval 5
```

## Event proxy

This runner has support for [sse-proxy](https://github.com/MartijnBraam/sse-proxy) for sending notifications to the
browser on task completion.

```bash
$ python3 drushqueued --database theaegirdatabase --eventproxy http://localhost:8088/broadcast/
```

## Event source

This runner can also host a eventsource webserver. Use the `--eventsource` option to start the server and specify the port

```bash
$ python3 drushqueued --database theaegirdatabase --eventsource 8088
```