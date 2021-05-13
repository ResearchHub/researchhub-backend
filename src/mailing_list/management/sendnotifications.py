"""
TODO: Create a command that sends email notifications under a few different
conditions:
    - when someone comments on a user's thread
    - when someone replies to a user's comment
    - etc...

To set this up we need a few things created in the db. Here's an example that
we can run manually:

1. Create a ThreadSubscription with none set to False and comments set to True

2. Create a user, Alice

3. Create an EmailRecipient with user set to Alice and email set to your actual
email address (so you can see if you receive anything)

Enter the python shell
```
>
> # 4. Create a Thread with created_by set to Alice
> from user.models import User
> alice = User.objects.get(pk=)
> from discussion.tests.helpers import create_comment, create_thread
> thread = create_thread(created_by=alice)
>
> # 5. Create a comment created by a user other than Alice
> # with the thread field set to the thread Alice created
> bob = User.objects.get(pk=)
> create_comment(created_by=bob, thread=thread)
>
```

from user.models import User
val = User.objects.get(pk=5)
regulus = User.objects.get(pk=3)
from discussion.tests.helpers import create_comment
from discussion.models import Comment, Thread
thread = Thread.objects.filter(created_by=val)[0]
comment = create_comment(created_by=regulus, thread=thread)
comment = create_comment(created_by=val, thread=thread)
from discussion.tests.helpers import create_comment, create_reply
comment = Comment.objects.filter(created_by=val)[0]
reply = create_reply(created_by=regulus, parent=comment)


6. Check your email and you should see something from RH

"""
