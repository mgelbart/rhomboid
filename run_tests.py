from main import main
import utils
import rubrics
import json
import os
from collections import OrderedDict
from datetime import datetime

THINGS_TO_TEST = {
	"open-course" : True,
	"open" : 		True,
	"update" : 		True,
	"close" : 		True,
	"fake-grading": True, # must have something above this on if this is on
	"return-one" : 	True,
	"return-all" : 	True
}

test_config_filename = "test_config.json"

lab_name="homework1"
g = None



if THINGS_TO_TEST["open-course"]:

	print('Opening Course\n')
	g = main("open", test_config_filename, ask_human=False)
	print('\n'*5)

if THINGS_TO_TEST["open"]:
	print("Opening Assessment\n")

	# open a lab// # Note: we keep the same GitHubLMS object just to make the test run faster.
	g = main("open", test_config_filename, aname=lab_name, gh_object=g, ask_human=False)
	print('\n'*5)

if THINGS_TO_TEST["update"]:
	print("Modifying assessment\n")

	NUMBER_OF_MODIFICATIONS = 2
	# modify the lab

	for i in range(NUMBER_OF_MODIFICATIONS):
		print("**** Update Number %d/%d" % (i+1, NUMBER_OF_MODIFICATIONS))
		filename = g.get_assessment_main_file_name(lab_name)
		a_contents = g._file_contents(g.staff_repo, filename)
		a_contents_updated = a_contents + "\nBLAH BLAH BLAH THESE ARE EDITS MADE ON %s\n" % datetime.strftime(datetime.now(), 'on %Y-%m-%d at %H:%M:%S')
		g._create_file(g.staff_repo, filename, a_contents_updated, overwrite=True)

		# update the lab after modifications
		g = main("update", test_config_filename, aname=lab_name, gh_object=g, ask_human=False)
		print('\n'*5)


if THINGS_TO_TEST["close"]:
	print("Closing assessment\n")
	g = main("close", test_config_filename, aname=lab_name, gh_object=g, ask_human=False)
	print('\n'*5)

if THINGS_TO_TEST["fake-grading"]:
	groups = g.load_student_groups(lab_name)
	print("Doing some fake grading\n")
	for group in groups:
		grades_path = "%s/forms/%s.json" % (lab_name, utils.group_to_str(group))
		# import pdb; pdb.set_trace()
		grades_string = g._file_contents(g.grades_repo, grades_path)
		grades = json.loads(grades_string, object_pairs_hook=OrderedDict)
		for exercise_name, row in grades.items():
			if isinstance(row, dict):
				for rubric_name, current_grade in row.items(): # give everything 2/2
					if current_grade == rubrics.DEFAULT_GRADES_FORM_SYMBOL:
						row[rubric_name] = 2
		# grades["PEER REVIEW"]["Peer Review"] = 3
		grades[utils.OVERALL_FEEDBACK_STR] = "Good job on this assignment. You get a gold star! :star:"
		grades_str = json.dumps(grades, indent=4)
		g._create_file(g.grades_repo, grades_path, grades_str, overwrite=True)
	print('\n'*5)

if THINGS_TO_TEST["return-one"]:
	print("Return the assessment\n")
	g = main("return", test_config_filename, aname=lab_name, gh_object=g, ask_human=False)
	print('\n'*5)

if THINGS_TO_TEST["return-all"]:
	print("Returning final grades\n")
	g = main("return", test_config_filename, gh_object=g, ask_human=False)
