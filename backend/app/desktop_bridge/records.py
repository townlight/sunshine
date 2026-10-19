"""Typed native-field translation. Business operations stay in Records."""

from app.desktop_bridge import schemas as dto
from app.requests import workflow


async def apply_command(session, req, actor, command):
    if isinstance(command, dto.FinishCommand):
        from app.requests import artifacts
        if command.action == "close-records-request":
            return await artifacts.close(session, req, actor)
        return await artifacts.fulfill(session, req, actor)
    workflow.ensure_active(req)
    data = command.payload
    if isinstance(command, dto.AssignCommand):
        return await workflow.assign_request(session, req, actor, assigned_to=data.assignedTo)
    if isinstance(command, dto.DeadlineCommand):
        return await workflow.set_deadline(session, req, actor, deadline=data.deadline, basis=data.deadlineBasis)
    if isinstance(command, dto.CalculateDeadlineCommand):
        return await workflow.calculate_deadline(
            session, req, actor, received_date=data.deadlineReceivedDate, rule_name=data.deadlineRuleName,
            day_count=int(data.deadlineDayCount), day_type=data.deadlineDayType, basis=data.deadlineBasis,
        )
    if isinstance(command, dto.ClarificationCommand):
        return await workflow.request_clarification(session, req, actor, note=data.clarificationNote)
    if isinstance(command, dto.MessageCommand):
        return await workflow.add_staff_message(session, req, actor, body=data.requestMessageBody)
    if isinstance(command, dto.SearchNoteCommand):
        return await workflow.record_search_note(session, req, actor, note=data.sourceNote, citation=data.citation)
    if isinstance(command, dto.SearchReceiptCommand):
        return await workflow.record_search_receipt(
            session, req, actor, query=data.searchQuery, locations=data.searchLocations,
            title=data.searchResultTitle, citation=data.searchResultCitation, summary=data.searchResultSummary,
            status=data.searchResultStatus, reviewer=data.searchReviewer,
        )
    if isinstance(command, dto.ExemptionNoteCommand):
        return await workflow.record_exemption_note(session, req, actor, note=data.exemptionNote)
    if isinstance(command, dto.ExemptionDecisionCommand):
        return await workflow.record_exemption_decision(
            session, req, actor, source=data.exemptionSource, kind=data.exemptionKind,
            finding=data.exemptionFinding, decision=data.exemptionDecision, basis=data.exemptionBasis,
            reviewer=data.exemptionReviewer,
        )
    if isinstance(command, dto.FeeEstimateCommand):
        return await workflow.estimate_fee(session, req, actor, estimate=data.feeEstimate)
    if isinstance(command, dto.FeeLineCommand):
        return await workflow.add_fee_line(session, req, actor, description=data.feeLineDescription,
                                          basis=data.feeScheduleBasis, amount=data.feeLineAmount)
    if isinstance(command, dto.FeeWaiverCommand):
        return await workflow.waive_fee(session, req, actor, reason=data.feeWaiverReason)
    if isinstance(command, dto.DraftCommand):
        return await workflow.save_response_draft(session, req, actor, text=data.responseDraft, citation=data.citation)
    if isinstance(command, dto.ApprovalCommand):
        return await workflow.approve_response(session, req, actor, note=data.approvalNote)
    raise ValueError("This Records operation is not supported.")
