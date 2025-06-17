variable "tiingo_scraper_image_uri" {
  description = "ECR image URI for the tiingo scraper Lambda"
  type        = string
}

variable "backfill_orchestrator_image_uri" {
  description = "ECR image URI for the backfill orchestrator Lambda"
  type        = string
}
variable "gdelt_scraper_image_uri" {
  description = "ECR image URI for the GDELT scraper Lambda"
  type        = string
}

variable "gdelt_backfill_orchestrator_image_uri" {
  description = "ECR image URI for the GDELT backfill orchestrator Lambda"
  type        = string
}