help me spec out a cli to interact with Monday.com. the goal will be to create the cli with python and compile it to a binary to run on linux, using packageinstaller.  i would like to use the httpx library instead of requests. I also want to use a library for cli args that make it easer.

The monday api docs are https://developer.monday.com/api-reference/reference/about-the-api-reference

you will need to review and find the docs for the following tasks

- Get all the information for a specific task by ID, this will include all fields, docs etc attached to the task.
- Post updates to a task by id.
- Create subitems on a task on boad.
- Create items on a board
- Status updates of a subitem
- Create Updates on a subitem