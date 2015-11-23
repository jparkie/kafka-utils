from __future__ import absolute_import
from __future__ import print_function
from __future__ import unicode_literals

import sys
from collections import defaultdict

from kafka import KafkaClient
from kazoo.exceptions import NoNodeError

from .offset_manager import OffsetManagerBase
from yelp_kafka_tool.util.zookeeper import ZK


class RenameGroup(OffsetManagerBase):

    @classmethod
    def setup_subparser(cls, subparsers):
        parser_rename_group = subparsers.add_parser(
            "rename_group",
            description="Rename specified consumer group ID to a new name. "
            "This tool shall migrate all offset metadata in Zookeeper.",
            add_help=False
        )
        parser_rename_group.add_argument(
            "-h", "--help", action="help",
            help="Show this help message and exit."
        )
        parser_rename_group.add_argument(
            'old_groupid',
            help="Consumer Group ID to be renamed."
        )
        parser_rename_group.add_argument(
            'new_groupid',
            help="New name for the consumer group ID."
        )
        parser_rename_group.set_defaults(command=cls.run)

    @classmethod
    def run(cls, args, cluster_config):
        if args.old_groupid == args.new_groupid:
            print(
                "Error: Old group ID and new group ID are the same.",
                file=sys.stderr
            )
            sys.exit(1)
        # Setup the Kafka client
        client = KafkaClient(cluster_config.broker_list)
        client.load_metadata_for_topics()

        topics_dict = cls.preprocess_args(
            args.old_groupid, None, None, cluster_config, client
        )
        with ZK(cluster_config) as zk:
            try:
                topics = zk.get_children(
                    "/consumers/{groupid}/offsets".format(
                        groupid=args.new_groupid
                    )
                )
            except NoNodeError:
                # Consumer Group ID doesn't exist.
                pass
            else:
                # Is the new consumer already subscribed to any of these topics?
                for topic in topics:
                    if topic in topics_dict:
                        print(
                            "Error: Consumer Group ID: {groupid} is already "
                            "subscribed to topic: {topic}.\nPlease delete this "
                            "topic from either group before re-running the "
                            "command.".format(
                                groupid=args.new_groupid,
                                topic=topic
                            ),
                            file=sys.stderr
                        )
                        sys.exit(1)
                # Let's confirm what the user intends to do.
                if topics:
                    in_str = (
                        "Consumer Group: {new_groupid} already exists.\nTopics "
                        "subscribed to by the consumer groups are listed "
                        "below:\n{old_groupid}: {old_group_topics}\n"
                        "{new_groupid}: {new_group_topics}\nDo you intend to merge "
                        "the two consumer groups? (y/n)".format(
                            old_groupid=args.old_groupid,
                            old_group_topics=topics_dict.keys(),
                            new_groupid=args.new_groupid,
                            new_group_topics=topics
                        )
                    )
                    cls.prompt_user_input(in_str)

            old_offsets = defaultdict(dict)
            for topic, partitions in topics_dict.iteritems():
                for partition in partitions:
                    node_info = zk.get(
                        "/consumers/{groupid}/offsets/{topic}/{partition}".format(
                            groupid=args.old_groupid,
                            topic=topic,
                            partition=partition
                        )
                    )
                    offset, _ = node_info
                    old_offsets[topic][partition] = offset

            old_base_path = "/consumers/{groupid}".format(
                groupid=args.old_groupid,
            )
            for topic, partition_offsets in old_offsets.iteritems():
                for partition, offset in partition_offsets.iteritems():
                    new_path = "/consumers/{groupid}/offsets/{topic}/{partition}".format(
                        groupid=args.new_groupid,
                        topic=topic,
                        partition=partition
                    )
                    try:
                        zk.create(new_path, value=bytes(offset), makepath=True)
                    except:
                        print(
                            "Error: Unable to migrate all metadata in Zookeeper. "
                            "Please re-run the command.",
                            file=sys.stderr
                        )
                        raise
            try:
                zk.delete(old_base_path, recursive=True)
            except:
                print(
                    "Error: Unable to migrate all metadata in Zookeeper. "
                    "Please re-run the command.",
                    file=sys.stderr
                )
                raise