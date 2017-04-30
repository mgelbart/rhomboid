# rhomboid
Rhomboid, a set of tools for delivering a course on GitHub

## Warnings

- This code has not yet been cleaned up. It's currently in a rough version.
- The code is currently set up to use GitHub Enterprise. I think it may be a matter of just changing [this line](https://github.com/mgelbart/rhomboid/blob/master/src/main.py#L8) and [this line](https://github.com/mgelbart/rhomboid/blob/master/src/main.py#L49) for it to work with github.com, but I haven't tested this yet.

## Demo

To see this tool in action, check out https://www.youtube.com/watch?v=zgiaBS4uUk0

## Installation / setting up

#### Setting up the code and libraries
0. Make sure you are using Python 3.5 (or higher probably works too)
1. Clone this repository.
3. Install with `pip install -r requirements.txt`
4. Set up a config file following `test_config.json` as a template.

#### Generate a Personal Access Token for the GitHub API

1. Go to https://github.ubc.ca/settings/tokens
2. Select "Generate new token"
3. Check the boxes for `repo` and `read:org` (the `repo` box should cause a couple of other boxes to get checked as well)
3. Select "Generate token" at the bottom
4. Keep the page open as you will need the token shortly. *It is your responsibility to keep this token safe. Treat it the same way you treat your password.**




## Basic usage:

```
python main.py [CONFIGFILE] [MODE] --name=<NAME>
```

In the above, `[CONFIGFILE]` is the path to your config file and `<NAME>` is the name of the assessment (e.g., `lab1`). The possible values of `[MODE]` are, currently:

* `init`: initialize the organization. Only needed once at the very beginning. This does:
  *  creates teams for different roles (students, TAs, fellows, instructors) and adds the relevant people
  *  create "home" repos for students
* `open`: open a course or assessment. 
  * If `--name` is absent then a course is opened. This does:
    * creates a team for the course and adds the relevant instructional staff members
    * creates the `_instructors` and `_students` repos for the course with associated permissions
    * creates a grades repo for each student for the course
    * creates a `grades_instructors` repo
  * If `--name` is present then the relevant assessment is opened. This does:
    * creates a repo for each student for the assessment
    * seeds these repositories with the relevant contents from the `_instructors` course repo
* `prepare`: preparing an assessment is the same as opening it except that the students do not get access to their repos. The point of this is for quizzes when time is short and we don't want to sit there waiting for lots of files to be copied. So we `prepare` the assessment in advance and then right at the start of the quiz we `open` it which just gives the students access fairly quickly. 
* `update`: notify students of changes to an assessment via pull requests. Do this if you change an open assessment in the `_instructors` repo and want to alert the students to the change. 
* `close`: close an assessment. This does:
  * students lose write access to their own submission repos
  * students gain read access to the submissions of all other students
  * json marking forms are created in the `grades_instructors` repository
* `return`: return a course or assessment. 
  * If `--name` is present then the relevant assessment is returned. This pushes the grades for the assessment to the students' grades repos and opens and issue to notify them. This should only be done after that assessment has been graded.
  * If `--name` is absent then the entire course is returned. This first tabulates (see below) and then reads the resulting CSV. It then pushes final course grades to the students and opens an issue to notify them. This should only be done after _all_ assessments have been graded and returned for the course.
* `tabulate`: tabulate the grades for a course (not for a particular assessment). This creates a `grades.csv` file in the `grades_instructors` repo showing a spreadsheet of the course grades.

Regarding the **Personal Access Token**: you can store this in an environment variable called `GITHUB_PAT` or enter it in manually each time.

## Example workflow for instructors

1. Run `init` to create the course.
2. The script will make a default `course_config.json` for you in the `_instructors` repository. (NOTE: the "course config" and the "config file" are two different things. The former defines which assignments your course contains, whereas the latter defines where your course lives on GitHub. This absolutely needs to be clarified/improved!) Make sure this is exactly the way you want it. If you need to make changes: abort, make changes, push changes, and `init` again. 
3. Put some assessments in the `_instructors` repository. The paths to these files must exactly match what you specified in your `course_config.json`. Furthermore, the `open` step will only copy things in the same directory as the main file. So if your main file is `labs/lab1/lab1.Rmd` then everything in `labs/lab1` will be copied to the students. The other contents of `labs` will **not** be copied. However, subdirectories will also be copied, like the contents of `labs/lab1/data`, for example.
4. Open an assessment.
5. (optional) Use `update` to make any necessary changes.
6. Close the assessment.
7. The TAs grade it and then return the assessment.
7. Repeat steps 4-7 throughout the term.
8. Tabulate the final grades and make sure then look OK.
9. Return the final grades

The format of the course config file is (as an example):

```
{
    "lab" : {
        "weight" : 0.4,
        "peer-review" : 0,
        "public-after-submit" : true,
        "main-file" : "labs/lab1/lab1.*",
        "main-dir" : "labs/lab1"
    },
    "exam" : {
        "weight" : 0.6,
        "peer-review" : 0,
        "public-after-submit" : false,
        "main-file" : "quiz/quiz2/quiz2.*",
        "main-dir" : "labs/lab1"
    }
}
```

* `lab` (string): the name of the assessment. This name will show up in the names of the relevant repositories.
* `public-after-submit` (boolean): whether or not students can see each other's work after the assessment is closed. 
* `weight` (float): the fraction of the course grade taken up by this assessment. The weights over all assessments must add up to 1.
* `peer-review` (integer): if zero, there will not be peer review on this assessment. If it is more than zero, it is the number of other students that each student needs to review. Note: turning on peer review only makes sense if `public-after-submit` is `true`. A future improvement would be to make the reviewees' repos visible to the reviewer, but for now this isn't implemented. 
* `main-file` (string): the path to the main file of the assessment. This is the file containing the rubric snippets. If `main-file` ends in `.*` instead of a normal extension, then the script will look for an `.ipynb`, `.Rmd`, and `.md` (in that order) to be the main file. 
* `main-dir` (string): this path controls what files will be copied to the students when an assessment is opened. Everything in this directory is copied. 

## Grading workflow for TAs

When an assessment is ready for grading, you will be tagged in an Issue to notify you.

#### Fill in the grades

1. Find the grading repository (see the config file)
2. Navigate to the particular lab/quiz that you are grading (a subdirectory of this repository)
3. You should see a big table. For each student, you should see a link to the submission repo and a link to the json grades form.
4. Fill out the json grades form for each student (TODO: add more detail on this).

Note: the feedback fields can be a little tricky. On the bad side, you need to be careful not to use double quotation marks, which accidentally close the field early on. If you want them, you can escape them with `/"`. On the good side, whatever you type in there gets rendered as Markdown when the students look at it in GitHub. This opens up some nice possibilities such as using the [GitHub markdown emoji](https://gist.github.com/rxaviers/7360908) in your feedback messages. For example, you can actually give your students a gold star! :star:

#### Push the grades to the students
1. (Recommended) Do a `git pull` in your clone of this repository and the github3.py code just in case there were updates.
2. From the directory containing the script, run 

 ```
 python main.py [CONFIGFILE] return --name=<NAME>
 ``` 
where `<NAME>` is the assessment name. 

3. The code will ask you for your API token (unless you stored it in an environment variable named `GITHUB_PAT`). Provide it and you should be good to go. To confirm that it worked, see that a "Marks Report" column was added to the big table. Try clicking on a couple of the reports and checking that they look right.

