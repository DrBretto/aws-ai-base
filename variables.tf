variable "tiingo_scraper_image_uri" {
  description = "ECR image URI for the tiingo scraper Lambda"
  type        = string
}

variable "backfill_orchestrator_image_uri" {
  description = "ECR image URI for the backfill orchestrator Lambda"
  type        = string
}