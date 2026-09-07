"""The port this gateway plugs into.

Any object providing these coroutines can back the MCP server. The API supplies
the real one; tests supply fakes. Keeping this a Protocol is what stops the
gateway from acquiring a dependency on the application.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from shared_schemas.tools import (
    CalculateTravelLoadInput,
    CalculateTravelLoadOutput,
    CheckRouteConstraintsInput,
    CheckRouteConstraintsOutput,
    CreateHumanReviewInput,
    CreateHumanReviewOutput,
    GetBookingRequirementsInput,
    GetBookingRequirementsOutput,
    GetPlaceConstraintsInput,
    GetPlaceConstraintsOutput,
    GetPlaceDetailsInput,
    GetPlaceDetailsOutput,
    GetRouteContextInput,
    GetRouteContextOutput,
    GetSourceEvidenceInput,
    GetSourceEvidenceOutput,
    GetTripContextInput,
    GetTripContextOutput,
    GetVerificationStatusInput,
    GetVerificationStatusOutput,
    GetWeatherContextInput,
    GetWeatherContextOutput,
    SaveTripDecisionInput,
    SaveTripDecisionOutput,
    SearchEvidenceInput,
    SearchEvidenceOutput,
    SearchTransportInput,
    SearchTransportOutput,
)


@runtime_checkable
class TravelBackend(Protocol):
    async def search_verified_evidence(self, args: SearchEvidenceInput) -> SearchEvidenceOutput: ...
    async def get_source_evidence(
        self, args: GetSourceEvidenceInput
    ) -> GetSourceEvidenceOutput: ...
    async def get_place_details(self, args: GetPlaceDetailsInput) -> GetPlaceDetailsOutput: ...
    async def get_place_constraints(
        self, args: GetPlaceConstraintsInput
    ) -> GetPlaceConstraintsOutput: ...
    async def search_transport(self, args: SearchTransportInput) -> SearchTransportOutput: ...
    async def get_route_context(self, args: GetRouteContextInput) -> GetRouteContextOutput: ...
    async def calculate_travel_load(
        self, args: CalculateTravelLoadInput
    ) -> CalculateTravelLoadOutput: ...
    async def check_route_constraints(
        self, args: CheckRouteConstraintsInput
    ) -> CheckRouteConstraintsOutput: ...
    async def get_booking_requirements(
        self, args: GetBookingRequirementsInput
    ) -> GetBookingRequirementsOutput: ...
    async def get_weather_context(
        self, args: GetWeatherContextInput
    ) -> GetWeatherContextOutput: ...
    async def get_verification_status(
        self, args: GetVerificationStatusInput
    ) -> GetVerificationStatusOutput: ...
    async def create_human_review_request(
        self, args: CreateHumanReviewInput
    ) -> CreateHumanReviewOutput: ...
    async def get_trip_context(self, args: GetTripContextInput) -> GetTripContextOutput: ...
    async def save_trip_decision(self, args: SaveTripDecisionInput) -> SaveTripDecisionOutput: ...
