from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken

from .models import User
from .serializers import RegisterSerializer, UserSerializer

BAD_CREDENTIALS = {"code": "BAD_CREDENTIALS", "detail": "Email yoki parol notoʻgʻri."}


def _auth_response(user, status_code=status.HTTP_200_OK):
    """Shape shared by register and login: {user, access, refresh}."""
    refresh = RefreshToken.for_user(user)
    return Response({
        "user": UserSerializer(user).data,
        "access": str(refresh.access_token),
        "refresh": str(refresh),
    }, status=status_code)


@api_view(["POST"])
@permission_classes([AllowAny])
def register(request):
    s = RegisterSerializer(data=request.data)
    s.is_valid(raise_exception=True)
    user = s.save()
    return _auth_response(user, status.HTTP_201_CREATED)


@api_view(["POST"])
@permission_classes([AllowAny])
def login(request):
    email = (request.data.get("email") or "").strip()
    password = request.data.get("password") or ""
    try:
        user = User.objects.get(email__iexact=email)
    except User.DoesNotExist:
        return Response(BAD_CREDENTIALS, status=400)
    if not user.check_password(password) or not user.is_active:
        return Response(BAD_CREDENTIALS, status=400)
    return _auth_response(user)


@api_view(["GET", "DELETE"])
@permission_classes([IsAuthenticated])
def me(request):
    """GET /api/auth/me/ (profile)  |  DELETE /api/auth/me/ (delete account)."""
    if request.method == "DELETE":
        request.user.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
    return Response(UserSerializer(request.user).data)
