from fastapi import APIRouter, Depends, Response

from src.controllers.access import analyst, current_user, owner
from src.services import reports
from src.services.exports import csv_result

router = APIRouter(prefix='/reports')


@router.get('')
def index(user=Depends(current_user)):
    return reports.list_reports(user['role'])


@router.post('/jobs/{job_id}/retry', status_code=202)
def retry(job_id: int, user=Depends(analyst)):
    return reports.retry_job(job_id, user['username'])


@router.get('/candidates/{candidate_id}')
def candidate(candidate_id: int, user=Depends(current_user)):
    return reports.get_candidate(candidate_id, user['role'])


@router.post('/candidates/{candidate_id}/publish')
def publish(candidate_id: int, user=Depends(owner)):
    return reports.publish_candidate(candidate_id, user['username'])


@router.get('/candidates/{candidate_id}/result.csv')
def candidate_csv(candidate_id: int, user=Depends(current_user)):
    detail = reports.get_candidate(candidate_id, user['role'])
    body = csv_result(dict(result=detail['result'], plan=detail['plan'],
                           snapshot_sha=detail['snapshot_sha'], draft=None, delta=detail['delta']))
    return Response(body, media_type='text/csv',
                    headers={'Content-Disposition': f'attachment; filename="umbrella-weekly-{candidate_id}.csv"'})


@router.get('/candidates/{candidate_id}/snapshot.json')
def candidate_snapshot(candidate_id: int, user=Depends(current_user)):
    detail = reports.get_candidate(candidate_id, user['role'], with_snapshot=True)
    return Response(detail['snapshot'], media_type='application/json',
                    headers={'Content-Disposition': f'attachment; filename="umbrella-weekly-{candidate_id}-snapshot.json"'})


@router.get('/{plan_id}')
def detail(plan_id: int, user=Depends(current_user)):
    return reports.get_report(plan_id, user['role'])


@router.post('/{plan_id}/recompute', status_code=202)
def recompute(plan_id: int, user=Depends(analyst)):
    return reports.request_recompute(plan_id, user['username'])
