from utils import *
from rubrics import check_for_bonus, BONUS_ALIAS, DEFAULT_GRADES_FORM_SYMBOL
from collections import defaultdict

# just totals up the assignment
# grades is a dict from exercise names to final grades
# FOR A PARTICULAR STUDENT OVER ALL ASSESSMENTS
def calculate_overall_course_grade_and_create_report(grades, course_config):

    overall_weights = {assname: value["weight"] for assname, value in course_config.items()}
    validate_weights(overall_weights)

    colnames = ["Assessment", "Weight", "Grade"]
    table = []

    overall_total_numerator = 0
    overall_total_denominator = 0

    for assessment_name in course_config:
        grade = grades[assessment_name]
        assessment_weight = overall_weights[assessment_name]

        overall_total_numerator += grade * assessment_weight
        overall_total_denominator += assessment_weight # leave it out of 100
        table.append([assessment_name, assessment_weight, grade])

    final_course_grade = overall_total_numerator/overall_total_denominator
    final_course_grade = min(100, final_course_grade) # cap at 100

    final_course_grade = round(final_course_grade)

    table.append([OVERALL_GRADE_COLUMN_NAME, "", "**%d%%**" % (final_course_grade)])

    report = tabulate_github(table, colnames)
    # print(report)

    return {"report" : report, "grade" : final_course_grade}


# In: grades (dict) for a particular student, as read from a json marks form
# Out: report (string)
# if weights_dict is not provided, then the report will not show the weights, or subtotals or a total
# FOR A PARTICULAR STUDENT AND A PARTICULAR ASSESSMENT
def calculate_single_assessment_grade_and_create_report(raw_grades, weights_dict, grades_mapping, rubric_images=None, score_only=True):

    s_out = ""

    total_numerator = 0
    total_denomiator = 0

    if score_only:
        exercise_table_headers = ["Points Earned", "Out Of"]
        overall_table_headers = ["Exercise Name", "Points Earned", "Out Of", "Feedback"]
        overall_table = []
    else:
        exercise_table_headers = ["Rubric", "Raw Score", "Scaled Score", "Points Earned", "Out Of"]
        overall_table_headers = ["Exercise Name", "Points Earned", "Out Of"]
        overall_table = []

    # the below is wrong because of bonus questions!
    # total_up_weights = lambda d: sum(d.values())
    # points_per_exercise = {exercise_name : total_up_weights(exercise_weights) for exercise_name, exercise_weights in weights_dict.items()}
    # total_points = total_up_weights(points_per_exercise)

    grades_dict = OrderedDict()
    for exercise_name, exercise_grades in raw_grades.items():

        if exercise_name == OVERALL_FEEDBACK_STR:
            continue

        is_bonus_exercise = weights_dict[exercise_name].get("is_bonus", False) or check_for_bonus(exercise_name)

        s_out += "#### %s\n\n" % exercise_name

        if rubric_images is not None:
            if exercise_name != "PEER REVIEW":
                try:
                    s_out += rubric_images[exercise_name] + "\n\n"
                except KeyError:
                    print("ERROR: Sorry, I can't find and exercise called %s. Please check the file on GitHub in the _instructors repo and investigate why it's not there. Thanks! Have a nice day." % exercise_name)
                    return {"report" : None, "grade" : None, "grades" : None}

        individual_exercise_table = []

        exercise_numerator = 0
        exercise_denominator = 0
        num_rubrics = 0
        at_least_one_question_ungraded = False
        at_least_one_question_graded = False
        for ev in sorted(exercise_grades): # sort the categories alphabetically, like code, mechanics etc
            # ev is a category, e.g. "Mechanics"
            if ev in ("feedback", "is_bonus"): # TODO: check if it's one of the rubrics, rather than it's NOT one of these. so that I can add fields later. 
                continue

            if exercise_grades[ev] == DEFAULT_GRADES_FORM_SYMBOL:
                at_least_one_question_ungraded = True
                continue
            else:
                at_least_one_question_graded = False

            try:
                score = float(exercise_grades[ev]) # in case the TA writes "2" instead of 2, the code works anyway
            except ValueError:
                print("Oh no. The grade entered in this form could not be converted to a float :(")
                return {"report" : None, "grade" : None, "grades" : None}

            if score < 0:
                print("Oh no. The grade entered in this form is negative :(")
                return {"report" : None, "grade" : None, "grades" : None}

            #don't list spark rubric if blank
            if (ev==BONUS_ALIAS and score==0):
                continue

            # weight = 1 if weights_dict is None else weights_dict[exercise_name][ev]
            weight = weights_dict[exercise_name][ev]
            if grades_mapping is not None:
                scaled_score = grades_mapping[score]
            else:
                scaled_score = score #/3

            # ok there's something complicated going on here
            # if it's spark points in a non-bonus exercise, then we want the denomiator of that RUBRIC to be zero
            # but it a bonus EXERCISE, then we want to actually treat all rubrics normally (can those ones have spark? evidently yes. haha. oh dear... that opens up some
            # edge cases.)
            # anyway, in that case we treat them normally and set the weight to zero downstream, when getting the total for the whole assignment

            if ev == BONUS_ALIAS:
                denominator_weight = 0 # it's Spark for a normal question, don't add to the denominator
            else:
                denominator_weight = weight
            exercise_denominator += denominator_weight
            exercise_numerator += scaled_score
            num_rubrics += 1

            # this is only necessary for legacy reasons.
            ev_print = ev.rstrip().rstrip("--").rstrip()

            if score_only:
                table_row = [scaled_score, denominator_weight]
            else:
                table_row = [ev_print, score, "%.0f%%" % (scaled_score*100), scaled_score*weight, denominator_weight]

            individual_exercise_table.append(table_row)

        if at_least_one_question_ungraded and at_least_one_question_graded:
            print("There is a problem. Some but not all of this assignment was graded. ")
            return {"report" : None, "grade" : None, "grades" : None}
        if at_least_one_question_ungraded and not at_least_one_question_graded:
            print("No grades were entered for this assignment. Assuming the person did not submit. ")
            return {"report" : "Assignment not graded by TA, presumably because it was not submitted (please notify us if otherwise!).", "grade" : 0, "grades" : defaultdict(float)}

        if num_rubrics > 1:
            individual_exercise_table.append(["**Total**", "", "", exercise_numerator, exercise_denominator])

        if individual_exercise_table: # not really needed-- but maybe it's empty??
            # if not (is_bonus_exercise and not feedback and exercise_numerator == 1): # don't show if it's a bonus you didn't do (optional)
            s_out += tabulate_github(individual_exercise_table, headers=exercise_table_headers)

        feedback = exercise_grades["feedback"]
        if feedback:
            s_out += "\n\n**Feedback:** %s\n\n" % feedback
        s_out += "\n\n"

        # exercise_weight = points_per_exercise[exercise_name] / total_points
        if score_only:
            overall_table.append([exercise_name, exercise_numerator, exercise_denominator, feedback])
        else:
            overall_table.append([exercise_name, exercise_numerator, exercise_denominator if not is_bonus_exercise else 0])

        if exercise_denominator == 0: # legacy version of bonus question that uses the actual spark rubric -- no longer used
            grades_dict[exercise_name] = exercise_numerator
        else:
            grades_dict[exercise_name] = exercise_numerator / exercise_denominator

        total_numerator += exercise_numerator 
        if not is_bonus_exercise: # check_for_bonus is more of a temporary hack
            total_denomiator += exercise_denominator

    overall_table.append(["**Total**", total_numerator, total_denomiator, ''])

    if score_only:
        s_out = "" # ignore all of the above and only show the overall evaluation
    else:
        s_out += "\n\n## Overall Evaluation\n\n"
    
    s_out += tabulate_github(overall_table, headers=overall_table_headers)

    assessment_overall_grade = total_numerator/total_denomiator*100.0
    s_out += "\n\nFinal grade: %.1f/%.1f = **%.0f%%**\n" % (total_numerator, total_denomiator, assessment_overall_grade)

    if OVERALL_FEEDBACK_STR in raw_grades and raw_grades[OVERALL_FEEDBACK_STR]:
        s_out += "\n\n## Overall Feedback\n\n" + raw_grades[OVERALL_FEEDBACK_STR]

    # don't round the assessment_overall_grade here because it will still be used in further calculations
    return {"report" : s_out, "grade" : assessment_overall_grade, "grades" : grades_dict}
