#!/usr/bin/python
# -*- coding: utf-8 -*-

# Programming contest management system
# Copyright © 2010-2011 Giovanni Mascellani <mascellani@poisson.phc.unipi.it>
# Copyright © 2010-2011 Stefano Maggiolo <s.maggiolo@gmail.com>
# Copyright © 2010-2011 Matteo Boscariol <boscarim@hotmail.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import yaml
import os
import sys
import codecs
import optparse

from cms.async import ServiceCoord
from cms.db.SQLAlchemyAll import metadata, Session, Task, Manager, Testcase, User, Contest, PublicTestcase, SubmissionFormatElement
from cms.service.ScoreType import ScoreTypes
from cms.async.AsyncLibrary import rpc_callback, Service, logger

class YamlImporter(Service):

    def __init__(self, shard):
        logger.initialize(ServiceCoord("YamlImporter", shard))
        logger.debug("YamlImporter.__init__")
        Service.__init__(self, shard)
        self.FS = self.connect_to(
            ServiceCoord("FileStorage", 0),
            sync=True)
        if not self.FS.connected:
            logger.error("Please run the FileStorage service.")
            self.exit()


    def get_params_for_contest(self, path, zero_time=False):
        """Given the path of a contest, extract the data from its
        contest.yaml file, and create a dictionary with the parameter to
        give to the Contest class. Since tasks and users need to be
        handled differently if we are doing an import or a reimport, we do
        not fill the dictionary with tasks' and users' information, but we
        return the lists of their names after the dictionay of parameters.
        """
        path = os.path.realpath(path)
        name = os.path.split(path)[1]
        conf = yaml.load(codecs.open(\
                os.path.join(path, "contest.yaml"),
                "r", "utf-8"))

        params = {"name": name}
        assert name == conf["nome_breve"]
        params["description"] = conf["nome"]
        params["token_initial"] = conf.get("token_initial", 0)
        params["token_max"] = conf.get("token_max", 0)
        params["token_total"] = conf.get("token_total", 0)
        params["token_min_interval"] = conf.get("token_min_interval", 0)
        params["token_gen_time"] = conf.get("token_gen_time", 1)
        if zero_time:
            params["start"] = 0
            params["stop"] = 0
        else:
            params["start"] = conf.get("inizio", 0)
            params["stop"] = conf.get("fine", 0)
        return params, conf["problemi"], conf["utenti"]


    def get_params_for_user(self, user_dict):
        """Given the dictionary of information of a user (extracted from
        contest.yaml), it fills another dictionary with the parameters to
        give to our class User.
        """
        params = {}
        params["username"] = user_dict["username"]
        params["password"] = user_dict["password"]
        name = user_dict.get("nome", "")
        surname = user_dict.get("cognome", user_dict["username"])
        params["real_name"] = " ".join([name, surname])
        params["ip"] = user_dict.get("ip", "0.0.0.0")
        params["hidden"] = "True" == user_dict.get("fake", "False")
        params["tokens"] = []
        return params


    def get_params_for_task(self, path):
        """Given the path of a task, this function put all needed data
        into FS, and fills the dictionary of parameters to pass to the
        class Task.
        """
        path = os.path.realpath(path)
        super_path, name = os.path.split(path)
        conf = yaml.load(codecs.open(\
                os.path.join(super_path, name + ".yaml"),
                "r", "utf-8"))

        params = {"name": name}
        assert name == conf["nome_breve"]
        params["title"] = conf["nome"]
        params["time_limit"] = conf["timeout"]
        params["memory_limit"] = conf["memlimit"]
        params["attachments"] = {} # FIXME - Use auxiliary
        with open(os.path.join(path, "testo", "testo.pdf")) as f:
            params["statement"] = self.FS.put_file(binary_data=f.read(),
                                                   description="PDF statement for task %s" % (name))
        params["task_type"] = Task.TASK_TYPE_BATCH
        params["submission_format"] = [SubmissionFormatElement("%s.%%l" % (name))]
        try:
            fd = open(os.path.join(path, "cor", "correttore"))
        except IOError:
            fd = None
        if fd != None:
            params["managers"] = {"checker": Manager(self.FS.put_file(fd, "Manager for task %s" % (name)))}
        else:
            params["managers"] = {}
        params["score_type"] = conf.get("score_type", ScoreTypes.SCORE_TYPE_SUM)
        params["score_parameters"] = conf.get("score_parameters", [])
        params["testcases"] = [Testcase(self.FS.put(os.path.join(path, "input",
                                                                 "input%d.txt" % (i)),
                                                    "Input %d for task %s" % (i, name)),
                                        self.FS.put(os.path.join(path, "output",
                                                                 "output%d.txt" % (i)),
                                                    "Output %d for task %s" % (i, name)))
                               for i in range(int(conf["n_input"]))]
        public_testcases = conf.get("risultati", "").split(",")
        if public_testcases == [""]:
            params["public_testcases"] = []
        else:
            params["public_testcases"] = map(lambda x: PublicTestcase(int(x)), public_testcases)
        params["token_initial"] = conf.get("token_initial", 0)
        params["token_max"] = conf.get("token_max", 0)
        params["token_total"] = conf.get("token_total", 0)
        params["token_min_interval"] = conf.get("token_min_interval", 0)
        params["token_gen_time"] = conf.get("token_gen_time", 60)
        return params


    def import_contest(self, path, zero_time=False):
        """Import a contest into the system.
        """
        params, tasks, users = self.get_params_for_contest(path, zero_time=zero_time)
        params["tasks"] = []
        for task in tasks:
            task_params = self.get_params_for_task(os.path.join(path, task))
            params["tasks"].append(Task(**task_params))
        params["users"] = []
        for user in users:
            user_params = self.get_params_for_user(user)
            params["users"].append(User(**user_params))
        return Contest(**params)


    def do_import(self, dir, drop, zero_time):
        if drop:
            metadata.drop_all()
        metadata.create_all()
        c = self.import_contest(dir, zero_time=zero_time)
        session = Session()
        session.add(c)
        session.commit()
        session.close()

if __name__ == "__main__":
    parser = optparse.OptionParser(usage="usage: %prog [options] contest_dir")
    parser.add_option("-z", "--zero-time",
                      dest="zero_time", help="set to zero contest start and stop time",
                      default=False, action="store_true")
    parser.add_option("-d", "--drop",
                      dest="drop", help="drop everything from the database before importing",
                      default=False, action="store_true")
    parser.add_option("-s", "--shard",
                      dest="shard", action="store", type="int", default=None)
    options, args = parser.parse_args()
    if len(args) != 1:
        parser.error("I need exactly one parameter, the contest directory")
    if options.shard is None:
        parser.error("The `-s' option is mandatory!")

    yaml_importer = YamlImporter(shard=options.shard)
    yaml_importer.do_import(dir=args[0], drop=options.drop, zero_time=options.zero_time)