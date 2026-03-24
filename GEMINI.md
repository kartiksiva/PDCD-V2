# GEMINI.md - PFCD Video-First v1 (Planning Context)

This directory serves as the foundation for the **PFCD Video-First v1** project, a fresh build focused on generating process documentation from video recordings as the primary source of truth.

## 📁 Directory Overview
This is a planning and design directory for an Azure-native AI agentic pipeline. It currently contains the core product requirements and architectural design documents.

## 📄 Key Files
- **`prd.md`**: The primary source of truth. It defines the "Video-First" vision, evidence priority (Video > Transcript), and the agentic workflow (Extraction -> Processing -> Reviewing).
- **`prd-review-20032026.md`**: Technical analysis of the PRD, highlighting risks in video/transcript alignment, cost management, and providing architectural recommendations (e.g., Evidence Graph, Correlation-IDs).

## 🚀 Project Vision
Build a system that extracts process flows from Teams recordings using Azure-managed AI services.
- **Evidence Priority**: 1. Video + Audio | 2. Transcript (Assistive) | 3. Audio | 4. Transcript (Fallback).
- **Output**: Process Definition Document (PDD) and SIPOC map.

## 🏗️ Technical Architecture (Azure Native)
- **AI Services**: Azure OpenAI (GPT-4o, GPT-4o-mini), Azure AI Speech, Azure AI Vision (OCR/Spatial).
- **Orchestration**: Event-driven via Azure Service Bus.
- **Persistence**: Azure Blob Storage (Media), Azure SQL/Cosmos DB (State/Metadata).

## 🛠️ Instructional Context
- **Surgical Changes**: When implementing features described in `prd.md`, prioritize modularity for the agentic pipeline.
- **Evidence-First**: All generated steps must be traceable back to source anchors (timestamps/frames).
- **Quality Gates**: Ensure every process step and SIPOC row has a valid `step_anchor` and `source_anchor`.
- **Cost Awareness**: Be mindful of Azure AI Vision and OpenAI costs; favor "Balanced" profiles unless "Quality" is requested.

## 📋 Status
**Phase**: Planning / Design (Ready for Technical Design and Skeleton Implementation).
