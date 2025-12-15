import os
import yaml
import argparse
import traceback
import time
from typing import Tuple
from datetime import datetime


def file_path(path):
    if os.path.isfile(path) and path.endswith('.yaml'):
        return path
    else:
        raise argparse.ArgumentTypeError(f"File path: {path} is invalid or non-yaml")


def valid_date(date):
    try:
        _ = datetime.strptime(date, '%Y-%m-%d')
    except ValueError:
        raise argparse.ArgumentTypeError(f"Given Date({date}) is invalid")
    return date


def get_rir_format_date(config_path: str) -> Tuple[str, str]:
    '''
    获取 rir 数据的最新日期，用于自动模式。
    该函数还会返回配置文件中的 output_dir 以确保自动模式下用户修改了配置文件也能正常运作。

    Parameters:

        config_path: str - 配置文件路径

    Returns:

        Tuple[str, str] - 最新日期和 output_dir

    '''
    with open(config_path, 'r') as cf:
        config = yaml.load(cf.read(), Loader=yaml.loader.SafeLoader)
        ouput_dir = config.get("output_dir", "./data/")  

        format_dir = config.get("rir_format_dir", "./rir_data/data/format/")
        if os.path.exists(format_dir):
            date_list_source = sorted(os.listdir(format_dir), reverse=True)
            date_list = []
            for d in date_list_source:
                try:
                    actual_date = valid_date(d)
                    date_list.append(actual_date)
                except:
                    continue
            if len(date_list) > 1:
                return date_list[1], ouput_dir
            else:
                raise ValueError(
                    f'Latest date need at least 2 dates data in {format_dir}, but only 1 or less date found: {date_list_source}')
        else:
            raise ValueError(f'Format directory {format_dir} not exists, please check your configuration.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='RIR Knowledge Base Fusion Processing CLI',
                                     epilog='Append your command, run different modules of the system or'
                                     'customize the configuration. However, we strongly recommend that'
                                     'you use YAML configuration files instead of CLI configuration'
                                     'related information. Because the configuration file can provide'
                                     'more configuration functions, such as database configuration, etc.',
                                     allow_abbrev=False)
    parser.add_argument('-c', '--conf', type=file_path,
                        help='YAML configuration file path, default is ./config.yaml')
    parser.add_argument('-d', '--date', type=valid_date,
                        help='Date of the data to be crawled, format is `%%Y-%%m-%%d`, eg. `2023-01-01`,'
                        'default is today. The priority of the date configuration is: CLI > YAML > Today.')

    # subparsers
    subparsers = parser.add_subparsers(dest='subparser_option', required=True,
                                       help='CLI options, supports `{run,db,auto}`, for help please type '
                                       '`setup.py {run,db,auto} -h` or refer to the CLI documentation')
    run_parser = subparsers.add_parser('run', help='Run specific module')
    db_parser = subparsers.add_parser('db', help='Write entity csv to database')
    auto_parser = subparsers.add_parser('auto', help='Auto mode')

    # rib options
    run_parser.add_argument('-rp', '--rib_parser', action='store_true',
                            help='Run RIB Parser, parse AS relations from RIB files')
    run_parser.add_argument('-rf', '--rib_formatter', action='store_true',
                            help='Run RIB Formatter, extract prefix AS pair from RIB files')

    # as, country, org options
    run_parser.add_argument('-af', '--as_formatter', action='store_true',
                            help='Run AS Entity Formatter, create AS entity')
    run_parser.add_argument('-cf', '--country_formatter', action='store_true',
                            help='Run Country Entity Formatter, create country entity')
    run_parser.add_argument('-of', '--org_formatter', action='store_true',
                            help='Run Org Entity Formatter, create organization entity')
    run_parser.add_argument('-og', '--org_group', action='store_true',
                            help='Run Org Group, generate organization grouping data. WARNING: Not recommonded to use -og to group org, you should turn to use -oa or -oi .')
    run_parser.add_argument('-oa', '--org_as', action='store_true',
                            help='Run AS Org group, generate organization grouping data by Whois/RDAP')
    run_parser.add_argument('-oi', '--org_ip', action='store_true',
                            help='Run IP Org group, generate organization grouping data by Whois/RDAP')
    run_parser.add_argument('-am', '--as_mail_key', action='store_true',
                            help='Run AS Mail Key, generate AS grouping data with mail key for org mapping')
    run_parser.add_argument('-im', '--ip_mail_key', action='store_true',
                            help='Run IP Mail Key, generate IP grouping data with mail key for org mapping')

    # ip options
    run_parser.add_argument('-ib', '--ip_bgp_formatter', action='store_true',
                            help='Run IP BGP Formatter, create IPv4/v6 BGP entities')
    run_parser.add_argument('-ir', '--ip_reg_formatter', action='store_true',
                            help='Run IP Reg Formatter, create IPv4/v6 inetnum, rdap and route entities')
    run_parser.add_argument('-id', '--ip_delegate_formatter', action='store_true',
                            help='Run IP Delegate Formatter, create IPv4/v6 delegate entities')

    # website options
    run_parser.add_argument('-df', '--dns_formatter', action='store_true',
                            help='Run DNS Entity Formatter, create website entity')
    run_parser.add_argument('-if', '--industry_formatter', action='store_true',
                            help='Run Industry Entity Formatter, create industry entity')

    # db options
    db_parser.add_argument('-a', '--all', action='store_true',
                           help='Write all entity csvs to database with default filenames')
    db_parser.add_argument('-ap', '--as_persistence', nargs='?', const='',
                           help='Write AS entity csv to database', metavar='filename')
    db_parser.add_argument('-cp', '--country_persistence', nargs='?', const='',
                           help='Write country entity csv to database', metavar='filename')
    db_parser.add_argument('-op', '--org_persistence', nargs='?', const='',
                           help='Write organization entity csv to database', metavar='filename')
    db_parser.add_argument('-wp', '--website_persistence', nargs='?', const='',
                           help='Write website (DNS) entity csv to database', metavar='filename')
    db_parser.add_argument('-in', '--industry_persistence', nargs='?', const='',
                           help='Write industry entity csv to database', metavar='filename')
    db_parser.add_argument('-ib', '--ip_bgp_persistence', nargs='?', const='',
                           help='Write IPv4 BGP entity csv to database', metavar='filename')
    db_parser.add_argument('-ib6', '--ipv6_bgp_persistence', nargs='?', const='',
                           help='Write IPv6 BGP entity csv to database', metavar='filename')
    db_parser.add_argument('-ad', '--as_delegate_persistence', nargs='?', const='',
                           help='Write AS delegate entity csv to database', metavar='filename')
    db_parser.add_argument('-id', '--ip_delegate_persistence', nargs='?', const='',
                           help='Write IPv4 delegate entity csv to database', metavar='filename')
    db_parser.add_argument('-id6', '--ipv6_delegate_persistence', nargs='?', const='',
                           help='Write IPv6 delegate entity csv to database', metavar='filename')
    db_parser.add_argument('-ii', '--ip_inetnum_persistence', nargs='?', const='',
                           help='Write IPv4 inetnum entity csv to database', metavar='filename')
    db_parser.add_argument('-ii6', '--ipv6_inetnum_persistence', nargs='?', const='',
                           help='Write IPv6 inetnum entity csv to database', metavar='filename')
    db_parser.add_argument('-ir', '--ip_rdap_persistence', nargs='?', const='',
                           help='Write IPv4 RDAP entity csv to database', metavar='filename')
    db_parser.add_argument('-ir6', '--ipv6_rdap_persistence', nargs='?', const='',
                           help='Write IPv6 RDAP entity csv to database', metavar='filename')
    db_parser.add_argument('-rt', '--ip_route_persistence', nargs='?', const='',
                           help='Write IPv4 route entity csv to database', metavar='filename')
    db_parser.add_argument('-rt6', '--ipv6_route_persistence', nargs='?', const='',
                           help='Write IPv6 route entity csv to database', metavar='filename')
    db_parser.add_argument('--drop_table',
                           help='Drop table from database', metavar='tablename')

    args = parser.parse_args()
    config_path = args.conf if args.conf else './config.yaml'
    date = 'latest'
    if args.date:
        date = args.date
    else:
        with open(config_path, 'r') as cf:
            config = yaml.load(cf.read(), Loader=yaml.loader.SafeLoader)
            try:
                date_str = config['current_date']
                date = valid_date(date_str)
            except Exception as e:
                # date = 'latest'
                date = datetime.now().strftime('%Y-%m-%d')

    from src.utils.logging_manager import logger
    try:
        logger.info("Start to run the system, PID: %s" % os.getpid())

        if args.subparser_option == 'run':
            if args.rib_parser:
                from src.as_entity.rib_parser import RIBParser
                obj = RIBParser(date, config_path, enable_DB=True)
                obj.run()
            if args.rib_formatter:
                from src.ip_entity.rib_formatter import RIBFormatter
                obj = RIBFormatter(date, config_path, enable_DB=True)
                obj.run()

            if args.org_group:
                logger.warn('Not recommonded to use -og to group org, you should turn to use -ow')
                from src.org_entity.org_group import OrgGroup
                obj = OrgGroup(date, config_path, enable_DB=True)
                obj.run()

            if args.as_mail_key or args.ip_mail_key:
                from src.org_entity.as_with_mail_key import ASWithMailKey
                obj = ASWithMailKey(date, config_path, enable_DB=True)
                if args.as_mail_key:
                    obj.run()
                if args.ip_mail_key:
                    obj.run(handle_as=False)
            if args.org_as:
                from src.org_entity.org_as import OrgAS
                obj = OrgAS(date, config_path, enable_DB=True)
                obj.run()
            if args.org_ip:
                from src.org_entity.org_ip import OrgIP
                obj = OrgIP(date, config_path, enable_DB=True)
                obj.run()
            if args.as_formatter:
                from src.as_entity.as_entity_formatter import ASEntityFormatter
                obj = ASEntityFormatter(date, config_path, enable_DB=True)
                obj.run()
            if args.country_formatter:
                from src.country_entity.country_entity_formatter import CountryEntityFormatter
                obj = CountryEntityFormatter(date, config_path, enable_DB=True)
                obj.run()
            if args.org_formatter:
                from src.org_entity.org_entity_formatter import OrgEntityFormatter
                obj = OrgEntityFormatter(date, config_path, enable_DB=True)
                obj.run()

            if args.ip_bgp_formatter:
                from src.ip_entity.ip_bgp_formatter import IPBGPFormatter
                obj = IPBGPFormatter(date, config_path, enable_DB=True)
                obj.run()
            if args.ip_reg_formatter:
                from src.ip_entity.ip_reg_formatter import IPRegFormatter
                obj = IPRegFormatter(date, config_path, enable_DB=True)
                obj.run()
            if args.ip_delegate_formatter:
                from src.ip_entity.ip_delegate_formatter import IPDelegateFormatter
                obj = IPDelegateFormatter(date, config_path, enable_DB=True)
                obj.run()

            if args.dns_formatter:
                from src.dns_entity.dns_entity_formatter import DNSEntityFormatter
                obj = DNSEntityFormatter(date, config_path, enable_DB=True)
                obj.run()
            if args.industry_formatter:
                from src.dns_entity.industry_entity_formatter import IndustryEntityFormatter
                obj = IndustryEntityFormatter(date, config_path, enable_DB=True)
                obj.run()

        elif args.subparser_option == 'db':
            from src.utils.entity_persistence import EntityPersistence
            ep = EntityPersistence(config_path, date)
            if args.all:
                ep.as_entity_prst()
                ep.country_entity_prst()
                ep.org_entity_prst()
                ep.website_entity_prst()
                ep.industry_entity_prst()
                ep.ip_bgp_entity_prst()
                ep.ipv6_bgp_entity_prst()
                ep.ip_inetnum_entity_prst()
                ep.ipv6_inetnum_entity_prst()
                ep.ip_rdap_entity_prst()
                ep.ipv6_rdap_entity_prst()
                ep.ip_route_entity_prst()
                ep.ipv6_route_entity_prst()
                ep.ip_delegate_entity_prst()
                ep.ipv6_delegate_entity_prst()
            if args.as_persistence is not None:
                ep.as_entity_prst(args.as_persistence)
            if args.country_persistence is not None:
                ep.country_entity_prst(args.country_persistence)
            if args.org_persistence is not None:
                ep.org_entity_prst(args.org_persistence)
            if args.website_persistence is not None:
                ep.website_entity_prst(args.website_persistence)
            if args.industry_persistence is not None:
                ep.industry_entity_prst(args.industry_persistence)
            if args.ip_bgp_persistence is not None:
                ep.ip_bgp_entity_prst(args.ip_bgp_persistence)
            if args.ipv6_bgp_persistence is not None:
                ep.ipv6_bgp_entity_prst(args.ipv6_bgp_persistence)
            if args.as_delegate_persistence is not None:
                ep.as_delegate_entity_prst(args.as_delegate_persistence)
            if args.ip_delegate_persistence is not None:
                ep.ip_delegate_entity_prst(args.ip_delegate_persistence)
            if args.ipv6_delegate_persistence is not None:
                ep.ipv6_delegate_entity_prst(args.ipv6_delegate_persistence)
            if args.ip_inetnum_persistence is not None:
                ep.ip_inetnum_entity_prst(args.ip_inetnum_persistence)
            if args.ipv6_inetnum_persistence is not None:
                ep.ipv6_inetnum_entity_prst(args.ipv6_inetnum_persistence)
            if args.ip_rdap_persistence is not None:
                ep.ip_rdap_entity_prst(args.ip_rdap_persistence)
            if args.ipv6_rdap_persistence is not None:
                ep.ipv6_rdap_entity_prst(args.ipv6_rdap_persistence)
            if args.ip_route_persistence is not None:
                ep.ip_route_entity_prst(args.ip_route_persistence)
            if args.ipv6_route_persistence is not None:
                ep.ipv6_route_entity_prst(args.ipv6_route_persistence)
            if args.drop_table is not None:
                ep.drop_table(args.drop_table)

        elif args.subparser_option == 'auto':

            if not args.date or date == '' or date is None or date.lower() == 'latest':
                date, ouput_dir = get_rir_format_date(config_path)
                logger.info(f'Latest rir data date is {date}')
            else:
                raise ValueError(
                    f'Auto mode only support latest date, but you have specified a date: {date}, if you want to run with specific date, please use run/db option.')

            real = datetime.now().strftime('%Y-%m-%d')
            while True:
                logger.info(f'开始执行融合处理实体格式化，当前数据日期为 {date}')
                try:
                    as_entity_family_success = True
                    ip_entity_family_success = True
                    dns_entity_family_success = True

                    try:
                        from src.org_entity.as_with_mail_key import ASWithMailKey
                        obj = ASWithMailKey(date, config_path, enable_DB=True)
                        obj.run()

                        from src.org_entity.org_as import OrgAS
                        obj = OrgAS(date, config_path, enable_DB=True)
                        obj.run()

                        from src.as_entity.as_entity_formatter import ASEntityFormatter
                        obj = ASEntityFormatter(date, config_path, enable_DB=True)
                        obj.run()

                        from src.country_entity.country_entity_formatter import CountryEntityFormatter
                        obj = CountryEntityFormatter(date, config_path, enable_DB=True)
                        obj.run()

                        from src.org_entity.org_entity_formatter import OrgEntityFormatter
                        obj = OrgEntityFormatter(date, config_path, enable_DB=True)
                        obj.run()
                    except Exception as e:
                        as_entity_family_success = False

                        # as_entity_del_path = os.path.join(ouput_dir, 'format', f'as_entity_{date}.csv')
                        # if os.path.exists(as_entity_del_path):
                        #     os.remove(as_entity_del_path)

                        # org_entity_del_path = os.path.join(ouput_dir, 'format', f'org_entity_{date}.csv')
                        # if os.path.exists(org_entity_del_path):
                        #     os.remove(org_entity_del_path)

                        # country_entity_del_path = os.path.join(ouput_dir, 'format', f'country_entity_{date}.csv')
                        # if os.path.exists(country_entity_del_path):
                        #     os.remove(country_entity_del_path)

                        logger.error(f'AS Entity Family Error: {e}')
                        logger.error(traceback.format_exc())

                    try:
                        from src.ip_entity.ip_bgp_formatter import IPBGPFormatter
                        obj = IPBGPFormatter(date, config_path, enable_DB=True)
                        obj.run()

                        from src.ip_entity.ip_reg_formatter import IPRegFormatter
                        obj = IPRegFormatter(date, config_path, enable_DB=True)
                        obj.run()

                        from src.ip_entity.ip_delegate_formatter import IPDelegateFormatter
                        obj = IPDelegateFormatter(date, config_path, enable_DB=True)
                        obj.run()
                    except Exception as e:
                        ip_entity_family_success = False

                        logger.error(f'IP Entity Family Error: {e}')
                        logger.error(traceback.format_exc())

                    try:
                        from src.dns_entity.industry_entity_formatter import IndustryEntityFormatter
                        obj = IndustryEntityFormatter(date, config_path, enable_DB=True)
                        obj.run()
                    except Exception as e:
                        dns_entity_family_success = False

                        logger.error(f'DNS Entity Family Error: {e}')
                        logger.error(traceback.format_exc())

                    from src.utils.entity_persistence import EntityPersistence
                    ep = EntityPersistence(config_path, date)
                    if as_entity_family_success:
                        ep.as_entity_prst()
                        ep.country_entity_prst()
                        ep.org_entity_prst()
                    if ip_entity_family_success:
                        # IP 相关实体支持 enable_DB 参数
                        pass
                    if dns_entity_family_success:
                        # ep.website_entity_prst()
                        ep.industry_entity_prst()
                except KeyboardInterrupt:
                    logger.info('KeyboardInterrupt, Exiting...')
                    exit(0)
                except Exception as e:
                    logger.error(f'Auto Mode Error: {e}')
                    logger.error(traceback.format_exc())
                    time.sleep(300)
                while real == datetime.now().strftime('%Y-%m-%d'):
                    logger.info(f'当前数据日期为 {date}，休眠 1 天...')
                    time.sleep(3600 * 24)
                real = datetime.now().strftime('%Y-%m-%d')
                date, ouput_dir = get_rir_format_date(config_path)

        logger.info("All Finish!")
    except Exception as e:
        logger.error(e)
        logger.error(traceback.format_exc())
        exit(1)
