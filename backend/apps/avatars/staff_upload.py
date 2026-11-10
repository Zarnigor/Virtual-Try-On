"""POST /api/staff/avatars/: added in part 2."""
from rest_framework.response import Response


def create_avatar(request):
    return Response({"detail": "not built yet"}, status=501)
