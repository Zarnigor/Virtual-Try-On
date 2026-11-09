from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from .models import Job
from .serializers import JobSerializer


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def get_job(request, pk):
    try:
        job = Job.objects.get(pk=pk, user=request.user)
    except Job.DoesNotExist:
        return Response(status=404)
    return Response(JobSerializer(job).data)
