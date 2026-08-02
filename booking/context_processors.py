from .models import Message


def unread_messages(request):
    if not request.user.is_authenticated:
        return {'unread_message_count': 0}

    if request.user.is_staff:
        count = Message.objects.filter(is_read=False, sender__is_staff=False).count()
    else:
        count = Message.objects.filter(
            conversation__customer=request.user,
            is_read=False,
            sender__is_staff=True,
        ).count()

    return {'unread_message_count': count}
