FROM nginx:1.25-alpine
LABEL authors="Jeremiah Hammond"

# Remove default config
RUN rm /etc/nginx/conf.d/default.conf

# Copy nginx config
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Expose port explicitly (documentation + clarity)
EXPOSE 80

# Run nginx in foreground
CMD ["nginx", "-g", "daemon off;"]