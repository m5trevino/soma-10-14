[ROLE::cross_agent_communication_protocol]
[MODE::strict_payload_routing]
[INPUT::agent_output_payload]
[OUTPUT::next_agent_input_payload]

[TYPE_MAP]
  AGENT → nexus | spark | falcon | eagle | owl | scout | drafter
  HANDOFF_TYPE → direct | conditional | batched | error_retry
  PAYLOAD_FORMAT → machine_talk_json | machine_talk_markdown | raw_artifact

[PIPELINE_SEQUENCE]
  nexus → spark → falcon → eagle → owl → scout → drafter
  scout_can_loop → owl (if_REWORK)
  drafter_can_loop → eagle (if_BLOCKED)

[HANDOFF_RULES]
  payload_must_contain → session_id | chatset_id | upstream_hash
  payload_must_not_contain → prose | markdown_fences | assistant_chatter
  validation → next_agent_validates_schema_before_processing
  failure → route_to_human_with_context_bundle

[CONTEXT_PRESERVATION]
  raw_chat → preserved_through_all_agents (never_mutated)
  nexus_blueprint → appended_to_not_replaced
  scout_report → injected_into_drafter_as_fix_list
  eagle_skeleton → consumed_by_owl_then_drafter

[ERROR_STATES]
  schema_mismatch → reject_payload + log_reason
  missing_required_field → reject_payload + flag_for_human
  circular_reference → detect_and_break_with_hash_check
  agent_timeout → retry_once_then_escalate

[EXEMPLAR_HANDOFF]
  {
    from_agent: "eagle",
    to_agent: "owl",
    handoff_type: "direct",
    payload: {
      session_id: "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
      chatset_id: "falcon-arch-v1.0",
      upstream_hash: "<ECHO THE HASH FROM THE INPUT PAYLOAD EXACTLY>",
      eagle_skeleton: { ... },
      falcon_architecture: { ... },
      spark_requirements: { ... }
    },
    validation: "schema_valid",
    timestamp: "2026-08-12T23:11:00Z"
  }
