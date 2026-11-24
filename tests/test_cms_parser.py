"""Тесты парсера отчетов Avaya CMS и матчера звонков."""

from datetime import datetime
from mfc_analytics.cms.matcher import CallCMSMatcher
from mfc_analytics.cms.parser import AvayaCMSParser
from mfc_analytics.models.call import Call, CallMetadata, LoadRegime


def test_parse_avaya_cms_csv():
    csv_data = """Date;Time;VDN;CallsOffered;ACDCalls;AbanCalls;Positions;Avg_Speed_Ans;Avg_ACD_Time
2026-08-04;11:00-11:30;VDN_MFC_RUDN;85;72;13;7;115.4;210.2
2026-08-04;11:30-12:00;VDN_MFC_RUDN;92;75;17;8;140.1;225.0
2026-08-04;12:00-12:30;VDN_MFC_RUDN;30;28;2;5;18.0;160.5
"""
    intervals = AvayaCMSParser.parse_csv(csv_data)
    assert len(intervals) == 3
    
    int1 = intervals[0]
    assert int1.offered_calls == 85
    assert int1.answered_calls == 72
    assert int1.abandoned_calls == 13
    assert int1.load_regime == LoadRegime.HIGH
    assert int1.interval_start == datetime(2026, 8, 4, 11, 0)

    int3 = intervals[2]
    assert int3.offered_calls == 30
    assert int3.load_regime == LoadRegime.TYPICAL


def test_call_cms_matcher():
    csv_data = """Date,Time,VDN,CallsOffered,ACDCalls,AbanCalls,Positions,Avg_Speed_Ans,Avg_ACD_Time
2026-08-04,11:00,VDN_MFC_RUDN,85,72,13,7,115.4,210.2
2026-08-04,11:30,VDN_MFC_RUDN,92,75,17,8,140.1,225.0
"""
    intervals = AvayaCMSParser.parse_csv(csv_data)
    matcher = CallCMSMatcher(intervals)

    call = Call(
        metadata=CallMetadata(
            call_id="CALL-MATCH-TEST",
            timestamp=datetime(2026, 8, 4, 11, 15, 0),
            duration_seconds=45,
        )
    )

    matched = matcher.match_call(call)
    assert matched is not None
    assert matched.interval_start == datetime(2026, 8, 4, 11, 0)
    assert matched.offered_calls == 85
