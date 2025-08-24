This package is for email tools for an agent app. 
You don't need to worry about integration, by means of you only 
change files under ./EmailTools/*

The tools are exposed out as functions with @tool decorator.

The Config object holds the variables, you can add more variables if you need.
I have instantiated a config object in __init__.py, config object should only be initialized once
and pass down to each component.

Finish Gmail client first. I will provide client secret and run it.