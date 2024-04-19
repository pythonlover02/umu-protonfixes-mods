""" Gets the game id and applies a fix if found
"""

import io
import os
import re
import sys
import urllib
import json
from functools import lru_cache
from importlib import import_module

try:
    from . import config
    from .util import check_internet
    from .checks import run_checks
    from .logger import log
except ImportError:
    import config
    from util import check_internet
    from checks import run_checks
    from logger import log



@lru_cache
def get_game_id() -> str:
    """ Trys to return the game id from environment variables
    """
    if 'UMU_ID' in os.environ:
        return os.environ['UMU_ID']
    if 'SteamAppId' in os.environ:
        return os.environ['SteamAppId']
    if 'SteamGameId' in os.environ:
        return os.environ['SteamGameId']
    if 'STEAM_COMPAT_DATA_PATH' in os.environ:
        return re.findall(r'\d+', os.environ['STEAM_COMPAT_DATA_PATH'])[-1]

    log.crit('Game ID not found in environment variables')
    return None


@lru_cache
def get_game_name() -> str:
    """ Trys to return the game name from environment variables
    """
    if os.environ.get('UMU_ID'):
        if os.path.isfile(os.environ['WINEPREFIX'] + '/game_title'):
            with open(os.environ['WINEPREFIX'] + '/game_title', 'r', encoding='utf-8') as file:
                return file.readline()

        if not check_internet():
            log.warn('No internet connection, can\'t fetch name')
            return 'UNKNOWN'

        try:
            # Fallback to 'none', if STORE isn't set
            store = os.getenv('STORE', 'none')
            url = f'https://umu.openwinecomponents.org/umu_api.php?umu_id={os.environ["UMU_ID"]}&store={store}'
            headers = {'User-Agent': 'Mozilla/5.0'}
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=5) as response:
                data = response.read()
                json_data = json.loads(data)
                title = json_data[0]['title']
            with open(os.environ['WINEPREFIX'] + '/game_title', 'w', encoding='utf-8') as file:
                file.write(title)
            return title
        except TimeoutError as ex:
            log.info('umu.openwinecomponents.org timed out')
            log.debug(f'TimeoutError occurred: {ex}')
        except OSError as ex:
            log.debug(f'OSError occurred: {ex}')
        except IndexError as ex:
            log.debug(f'IndexError occurred: {ex}')
        except UnicodeDecodeError as ex:
            log.debug(f'UnicodeDecodeError occurred: {ex}')
    else:
        try:
            game_library = re.findall(r'.*/steamapps', os.environ['PWD'], re.IGNORECASE)[-1]
            game_manifest = os.path.join(game_library, f'appmanifest_{get_game_id()}.acf')

            with io.open(game_manifest, 'r', encoding='utf-8') as appmanifest:
                for xline in appmanifest.readlines():
                    if 'name' in xline.strip():
                        name = re.findall(r'"[^"]+"', xline, re.UNICODE)[-1]
                        return name
        except OSError:
            pass
        except IndexError:
            pass
        except UnicodeDecodeError:
            pass

    return 'UNKNOWN'


def get_store_name(store: str) -> str:
    """ Mapping for store identifier to store name
    """
    return {
        'amazon': 'Amazon',
        'battlenet': 'Battle.net',
        'ea': 'EA',
        'egs': 'EGS',
        'gog': 'GOG',
        'humble': 'Humble',
        'itchio': 'Itch.io',
        'steam': 'Steam',
        'ubisoft': 'Ubisoft',
        'zoomplatform': 'ZOOM Platform'
    }.get(store, None)


def get_module_name(game_id: str, default: bool = False, local: bool = False) -> str:
    """ Creates the name of a gamefix module, which can be imported
    """
    store = 'umu'
    if os.environ.get('STORE'):
        store = os.environ.get('STORE').lower()
    elif game_id.isnumeric():
        store = 'steam'

    if store != 'steam':
        log.info(f'Non-steam game {get_game_name()} ({game_id})')

        store_name = get_store_name(store)
        if store_name:
            log.info(f'{store_name} store specified, using {store_name} database')
        else:
            log.info('No store specified, using UMU database')
            store = 'umu'

    return (f'protonfixes.gamefixes-{store}.' if not local else 'localfixes.') +\
           (game_id if not default else 'default')


def _run_fix_local(game_id: str, default: bool = False) -> bool:
    """ Check if a local gamefix is available first and run it
    """
    localpath = os.path.expanduser('~/.config/protonfixes/localfixes')
    module_name =  game_id if not default else 'default'

    # Check if local gamefix exists
    if not os.path.isfile(os.path.join(localpath, module_name + '.py')):
        return False

    # Ensure local gamefixes are importable as modules via PATH
    with open(os.path.join(localpath, '__init__.py'), 'a', encoding='utf-8'):
        sys.path.append(os.path.expanduser('~/.config/protonfixes'))

    # Run fix
    return _run_fix(game_id, default, True)


def _run_fix(game_id: str, default: bool = False, local: bool = False) -> bool:
    """ Private function, which actually executes gamefixes
    """
    fix_type = 'protonfix' if not default else 'defaults'
    scope    = 'global' if not local else 'local'

    try:
        module_name = get_module_name(game_id, default, local)
        game_module = import_module(module_name)

        log.info(f'Using {scope} {fix_type} for {get_game_name()} ({game_id})')
        game_module.main()
    except ImportError:
        log.info(f'No {scope} {fix_type} found for {get_game_name()} ({game_id})')
        return False
    return True


def run_fix(game_id: str) -> None:
    """ Loads a gamefix module by it's gameid
        local fixes prevent global fixes from being executed
    """
    if game_id is None:
        return

    if config.enable_checks:
        run_checks()

    # execute default.py (local)
    if not _run_fix_local(game_id, True) and config.enable_global_fixes:
        _run_fix(game_id, True) # global

    # execute <game_id>.py (local)
    if not _run_fix_local(game_id, False) and config.enable_global_fixes:
        _run_fix(game_id, False) # global


def main() -> None:
    """ Runs the gamefix
    """
    check_args = [
        'iscriptevaluator.exe' in sys.argv[2],
        'getcompatpath' in sys.argv[1],
        'getnativepath' in sys.argv[1],
    ]

    if any(check_args):
        log.debug(str(sys.argv))
        log.debug('Not running protonfixes for setup runs')
        return

    log.info('Running protonfixes')
    run_fix(get_game_id())
