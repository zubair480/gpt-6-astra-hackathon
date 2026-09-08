"""Offline consistency checks for actual protected-provider audit exports.

This does not authenticate a provider, prove masking, or prove actions executed.
Supply the complete run beginning with its initial request, never only its tail.
Keep the synthetic-value oracle in memory and out of exported reports.
"""
from .evidence import require, strings, validate_audit


def validate_provider_chain(entries, private_values, minimum_frames=2):
    """Check image/text evidence and root-to-tail Responses tool-result linkage.

    Entries must describe exactly one completed run in chronological order.
    The result names *proposed* transitions, because the current audit does not
    export per-request browser origin/tab identity or local execution receipts.
    """
    summary = validate_audit(entries, private_values, minimum_frames)
    require(all(entry.get('status') == 'responded' for entry in entries),
            'Incomplete run contains unsuccessful or unsent records')
    previous = None
    seen_response_ids = set()
    transitions = []
    for entry in entries:
        require(entry.get('source') == 'web', 'Evidence is not from the ordinary browser path')
        require(entry.get('transmitted') is True, 'Successful transport is not recorded')
        status = entry.get('http_status')
        require(isinstance(status, int) and 200 <= status < 300,
                'Successful HTTP status is not recorded')
        response_id = entry['response_id']
        require(response_id not in seen_response_ids, 'Duplicate provider response ID')
        seen_response_ids.add(response_id)
        payload = entry['payload']
        require(payload.get('model') == 'gpt-6-astra', 'Unexpected requested provider model')
        # Provider currently rebuilds every tool screenshot from this fresh frame.
        # Checking all occurrences closes the older-history/crop loophole.
        current = 'data:image/png;base64,' + entry['image_base64']
        images = [value for value in strings(payload) if value.startswith('data:image/')]
        require(all(value == current for value in images),
                'Additional outbound image needs independent pixel/hash verification')
        inputs = payload.get('input', [])
        require(isinstance(inputs, list), 'Unexpected provider input format')
        results = [item for item in inputs if isinstance(item, dict) and
                   item.get('type') in ('computer_call_output', 'function_call_output')]
        if previous is None:
            require(not payload.get('previous_response_id'),
                    'Missing initial request: retained provider history is unaudited')
            require(not results, 'Initial request unexpectedly contains tool results')
        else:
            require(payload.get('previous_response_id') == previous['response_id'],
                    'Provider history chain does not match preceding receipt')
            calls = [item for item in previous.get('response_output', []) if
                     item.get('type') in ('computer_call', 'function_call')]
            require(bool(calls), 'Follow-up lacks recorded preceding provider calls')
            expected = [(item.get('call_id'), item['type'] + '_output') for item in calls]
            actual = [(item.get('call_id'), item['type']) for item in results]
            require(all(isinstance(call_id, str) and call_id for call_id, _ in expected),
                    'Provider call identity missing')
            require(all(isinstance(call_id, str) and call_id for call_id, _ in actual),
                    'Tool result identity missing')
            require(len(set(expected)) == len(expected), 'Duplicate preceding provider call identity')
            require(sorted(actual) == sorted(expected),
                    'Follow-up results do not exactly match preceding provider calls')
            proposed = []
            for call in calls:
                if call['type'] == 'function_call':
                    proposed.append(call.get('name', 'unknown_function'))
                else:
                    actions = call.get('actions', [call['action']] if 'action' in call else [])
                    proposed.extend(action.get('type', 'unknown_action') for action in actions)
            transitions.append({'request_id': entry['request_id'],
                                'previous_response_id': previous['response_id'],
                                'frame_changed': entry['frame_hash'] != previous['frame_hash'],
                                'proposed_actions': proposed})
        previous = entry
    return {**summary, 'linked_followups': transitions,
            'authenticity': 'requires independently observed live transport',
            'pixel_masking': 'requires independent pixel oracle',
            'executed_transitions': 'requires browser origin/tab and execution evidence'}
