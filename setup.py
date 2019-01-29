import platform
import os
import getpass
import sys
from crontab import CronTab
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session
from scrapebot.configuration import Configuration
from scrapebot.database import base, User, Instance


def main():
    print('Welcome to the ScrapeBot setup')

    config = get_config()
    instance_name = check_minimal_config(config)

    print('Continuing to the database')
    print('- connecting to ' + config.config.get('Database', 'host', fallback='localhost'))
    try:
        engine = get_engine(config)
        base.metadata.create_all(engine)
        db = get_db(engine)
    except:
        print('- uh, there is a problem with connecting to your database ...')
        exit(3)
    print('- read tables: ' + ', '.join(base.metadata.tables.keys()))
    users = db.query(User).order_by(User.created).all()
    user: User = None
    if len(users) == 0:
        print('- the database currently does not contain any users, so we will create one')
        username = read_forcefully('- what name should this user listen to', 'root')
        email = read_forcefully('- and what is this user\'s email address')
        root = User(name=username, email=email)
        password = root.create_password()
        db.add(root)
        db.commit()
        user = db.query(User).filter(User.name == username).one()
        print('- default user ("' + username + '" with password "' + password + '", without quotes) created')
    else:
        print('- one or many users available')
        user = db.query(User).filter(User.name == 'root').first()
        if user is None:
            user = users[0]

    print('Checking this instance')
    this_instance = db.query(Instance).filter(Instance.name == instance_name)
    print('- it is called ' + instance_name)
    if this_instance.count() == 0:
        db.add(Instance(name=instance_name, owner_uid=user.uid))
        db.commit()
        print('- instance newly registered and ascribed to user "' + user.name + '"')
    else:
        print('- instance name already registered, meaning that it has been used elsewhere')
        if read_bool_forcefully('- is this on purpose'):
            print('- okay, fair enough, proceeding ...')
        else:
            instance_name = read_forcefully('- so how should this instance be called')
            config.add_value('Instance', 'Name', instance_name)
            config.write()
            print('- alright, updated "config.ini"')
            db.add(Instance(name=instance_name, owner_uid=user.uid))
            db.commit()
            print('- instance newly registered and ascribed to user "' + user.name + '"')
    print('- browser-wise this instance will use ' + config.config.get('Instance', 'browser', fallback='Firefox'))

    print('Finishing up')
    print('- instance should be ready to use')
    print('- to run it once, use the script "scrapebot.py"')
    if platform.system() == 'Linux':
        print('- to run it regularly and since you are using Linux, I recommend a cronjob')
        os_user = getpass.getuser()
        if read_bool_forcefully('- install cronjob for ' + os_user + ' now'):
            cron = CronTab(user=os_user)
            cron.remove_all(comment='ScrapeBot // ' + instance_name)
            cronjob = cron.new(command='cd ' + os.getcwd() + ' && ' + sys.executable +
                                       ' scrapebot.py >> /var/log/scrapebot_cron.log',
                               comment='ScrapeBot // ' + instance_name)
            cronjob.minute.every(2)
            cron.write()
    else:
        print('- to run it regularly (which is what you want), you may want to use Windows Task Scheduler or the like')
    print('---------')
    print('Thanks for using; please direct any questions and pull requests to https://github.com/marhai/scrapebot')


def get_config(create_if_necessary=True):
    if not os.access('config.ini', os.R_OK) and create_if_necessary:
        config = setup_config()
        print('Reading newly created config.ini')
        return config
    elif not os.access('config.ini', os.R_OK):
        print('Configuration (config.ini) not found (have you tried running "setup.py" first?')
        exit(3)
    else:
        print('Configuration file "config.ini" found')
        return Configuration()


def setup_config():
    print('No configuration file ("config.ini") found, so let\'s create it in six easy steps:')
    config = Configuration()
    print('(1) We first need access to the main MySQL database.' +
          'Specify the all the necessary credentials on where to find it!')
    config.add_value('Database', 'Host', read_forcefully('- Database: Host', 'localhost'))
    config.add_value('Database', 'User', read_forcefully('- Database: User', 'root'))
    config.add_value('Database', 'Password', read_forcefully('- Database: Password'))
    config.add_value('Database', 'Database', read_forcefully('- Database: Database Name', 'scrapebot'))
    print('(2) Next, we need to specify this very instance.')
    config.add_value('Instance', 'Name', read_forcefully('- Instance name'))
    print('(3) Assuming you have installed all necessary prerequisites, what browser will this instance run.')
    browser = read_forcefully('- Browser', 'Firefox')
    config.add_value('Instance', 'Browser', browser)
    if read_bool_forcefully('- Do you want to specify the path to ' + browser + '\'s binary'):
        config.add_value('Instance', 'BrowserBinary', read_forcefully('- Path to binary'))
    if read_bool_forcefully('- Do you want to change this browser\'s default user-agent string'):
        config.add_value('Instance', 'BrowserUserAgent', read_forcefully('- Full user-agent string'))
    config.add_value('Instance', 'BrowserWidth', read_numeric_forcefully('- Browser width [in pixel]', 1024))
    config.add_value('Instance', 'BrowserHeight', read_numeric_forcefully('- Browser height [in pixel]', 768))
    print('(4) Also, to simulate human surf behavior, this instance introduces random delays. ' +
          'Well, they are not completely random, though. You can set an approximate delay in seconds.')
    config.add_value('Instance', 'Timeout', read_numeric_forcefully('- Rough browser delay [in seconds]', 1))
    print('(5) In case a recipe wants to take screenshots, where should these screenshots be stored?')
    screenshot_dir = read_forcefully('- Directory for screenshots', 'screenshots/')
    if not screenshot_dir.endswith('/'):
        screenshot_dir = screenshot_dir + '/'
    config.add_value('Instance', 'ScreenshotDirectory', screenshot_dir)
    if not os.access(screenshot_dir, os.W_OK):
        if os.access(screenshot_dir, os.R_OK):
            print('- This directory, although it exists, is not writable for python scripts. Please fix that!')
        else:
            if read_bool_forcefully('- Directory does not exist. Create it now'):
                os.makedirs(screenshot_dir)
                print('- ' + screenshot_dir + ' created successfully')
    print('(6) If you want this instance to also serve as web frontend, you need to give it a means to send emails.')
    if read_bool_forcefully('- Will this (also) be a web frontend'):
        print('- Okay, well, in this case, let us add some information on that SMTP (!) server.')
        config.add_value('Email', 'Host', read_forcefully('- SMTP: Host'))
        tls = read_bool_forcefully('- Should this be TLS-encrypted')
        config.add_value('Email', 'TLS', tls)
        config.add_value('Email', 'Port', read_numeric_forcefully('- Which port should be used', (587 if tls else 25)))
        config.add_value('Email', 'User', read_forcefully('- Email: User'))
        config.add_value('Email', 'Password', read_forcefully('- Email: Password'))
    print('Thanks, that is all. Now let me just create this "config.ini" for you ...')
    if config.write():
        print('- Done!')
        return config
    else:
        print('- Argh, I am sorry but there was an error while creating the file. ' +
              'Do I have writing permissions in the current directory?')
        exit(3)


def read_forcefully(line, default=''):
    if default != '':
        line = line + ' (default is "' + default + '", to accept just hit return)'
    value = input(line + ': ').strip()
    if value == '':
        if default == '':
            print('- This information is obligatory!')
            return read_forcefully(line)
        else:
            print('- Using the default value, "' + default + '"')
            return default
    else:
        return value


def read_bool_forcefully(line):
    value = input(line + ' ("y" or "n", default is "y" if you just hit return): ').strip().lower()
    if value == '' or value == 'y' or value == 'yes':
        return True
    elif value != 'n' and value != 'no':
        print('- Assuming that this means "no"')
    return False


def read_numeric_forcefully(line, default=None):
    if default != '':
        line = line + ' (default is ' + str(default) + ', to accept just hit return)'
    value = input(line + ': ').strip()
    if value == '':
        if default is None:
            print('- This information is really necessary, please enter a number!')
            return read_numeric_forcefully(line)
        else:
            print('- Using the default value, ' + str(default))
            return int(default)


def check_minimal_config(config):
    config_sections = config.config.sections()
    if 'Database' not in config_sections or 'Instance' not in config_sections:
        print('- one or both obligatory section(s) "Database" and "Instance" not found')
        exit(3)
    elif 'Email' not in config_sections:
        print('- Email settings not configured so this instance cannot be the web frontend')
    if config.config.get('Database', 'password', fallback=None) is None:
        print('- database password not configured')
        exit(3)
    instance_name = config.config.get('Instance', 'name', fallback='')
    if instance_name == '':
        print('- instance name not configured')
        exit(3)
    else:
        return instance_name


def get_engine(config):
    return create_engine(config.get_db_engine_string(), encoding='utf-8')


def get_db(engine):
    session_factory = sessionmaker(bind=engine)
    return scoped_session(session_factory)


if __name__ == '__main__':
    main()